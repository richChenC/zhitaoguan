"""Process-local database maintenance gate; restore never races open connections."""
from contextlib import contextmanager
from threading import Condition, RLock, get_ident


class MaintenanceGate:
    def __init__(self):
        self.condition = Condition(RLock())
        self.readers = {}
        self.owner = None
        self.depth = 0
        self.waiters = 0

    def enter(self):
        ident = get_ident()
        with self.condition:
            while self.owner not in (None, ident) or (self.waiters and ident not in self.readers and self.owner != ident):
                self.condition.wait()
            self.readers[ident] = self.readers.get(ident, 0) + 1

    def leave(self):
        ident = get_ident()
        with self.condition:
            count = self.readers.get(ident, 0)
            if count > 1:
                self.readers[ident] = count - 1
            else:
                self.readers.pop(ident, None)
            self.condition.notify_all()

    @contextmanager
    def shared(self):
        self.enter()
        try:
            yield
        finally:
            self.leave()

    @contextmanager
    def exclusive(self):
        ident = get_ident()
        with self.condition:
            if self.owner == ident:
                self.depth += 1
            else:
                if ident in self.readers:
                    raise RuntimeError('不能在活动数据库事务中发起整库维护')
                self.waiters += 1
                try:
                    while self.owner is not None or self.readers:
                        self.condition.wait()
                    self.owner, self.depth = ident, 1
                finally:
                    self.waiters -= 1
        try:
            yield
        finally:
            with self.condition:
                self.depth -= 1
                if not self.depth:
                    self.owner = None
                self.condition.notify_all()


GATE = MaintenanceGate()
