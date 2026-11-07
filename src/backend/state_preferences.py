"""One persisted direction preference shared by every local recognition entry."""
from contextlib import nullcontext

try:
    from . import local_security
except ImportError:
    import local_security


def writable():
    return local_security.can_any('settings.manage', 'state.write', 'data.import')


def settings(server, connection=None):
    with nullcontext(connection) if connection is not None else server.connect() as db:
        row = db.execute('SELECT shift_direction FROM state_preferences WHERE id=1').fetchone()
        return {'shift_direction': row[0] if row else '1',
                'initialized': row is not None, 'writable': writable()}


def save(server, data):
    if not isinstance(data, dict) or set(data) - {'shift_direction', 'initialize_only'}:
        raise ValueError('移位方向设置格式无效')
    value = data.get('shift_direction')
    if not isinstance(value, str) or value not in ('1', '-1', 'pending'):
        raise ValueError('无符号移位默认方向应为正向、负向或留待核对')
    if type(data.get('initialize_only', False)) is not bool:
        raise ValueError('移位方向初始化选项无效')
    if not writable():
        if data.get('initialize_only'):
            return settings(server)
        raise local_security.AccessError('当前账户没有修改移位方向设置的权限')
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = settings(server, db)
        if data.get('initialize_only') and current['initialized']:
            return current
        db.execute('INSERT INTO state_preferences VALUES(1,?) ON CONFLICT(id) DO UPDATE SET shift_direction=excluded.shift_direction',
                   (value,))
        if not current['initialized'] or current['shift_direction'] != value:
            labels = {'1': '正向（+）', '-1': '负向（−）', 'pending': '留待核对'}
            server._log_operation('state_direction_setting', 'state_preferences',
                                  f"无符号移位默认方向：{labels[current['shift_direction']]} → {labels[value]}",
                                  1, connection=db)
            # Existing imports may have been held for direction confirmation.
            # Resolve only those candidates whose sole blocker was this setting.
            try:
                from . import inspection_states
            except ImportError:
                import inspection_states
            inspection_states.refresh_default_direction(server, db, value)
        return settings(server, db)


def direction(server, connection=None):
    return settings(server, connection)['shift_direction']


def resolve(distance, default_direction):
    if default_direction not in ('1', '-1', 'pending'):
        raise ValueError('无符号移位默认方向无效')
    return (None, distance) if default_direction == 'pending' else (float(default_direction) * distance, None)
