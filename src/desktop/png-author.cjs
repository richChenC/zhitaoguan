'use strict';

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const name = Buffer.from(type, 'ascii');
  const size = Buffer.alloc(4);
  const checksum = Buffer.alloc(4);
  size.writeUInt32BE(data.length);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([size, name, data, checksum]);
}

function withPngAuthor(image, username) {
  const signature = Buffer.from('89504e470d0a1a0a', 'hex');
  if (!Buffer.isBuffer(image) || !image.subarray(0, 8).equals(signature) ||
      !/^[a-z0-9][a-z0-9_.-]{1,63}$/.test(username)) throw new Error('图片或账户信息无效');
  let offset = 8;
  const parts = [signature];
  let ended = false;
  while (offset + 12 <= image.length) {
    const length = image.readUInt32BE(offset);
    const end = offset + 12 + length;
    if (end > image.length) throw new Error('图片数据不完整');
    const type = image.toString('ascii', offset + 4, offset + 8);
    const data = image.subarray(offset + 8, offset + 8 + length);
    if (type === 'IEND') {
      parts.push(chunk('tEXt', Buffer.from(`Author\0${username}`, 'ascii')));
      parts.push(chunk('tEXt', Buffer.from(`Creation Time\0${new Date().toISOString()}`, 'ascii')));
      parts.push(image.subarray(offset, end));
      ended = true;
      offset = end;
      break;
    }
    if (!(type === 'tEXt' && /^(Author|Creation Time)\0/.test(data.toString('latin1')))) {
      parts.push(image.subarray(offset, end));
    }
    offset = end;
  }
  if (!ended || offset !== image.length) throw new Error('图片数据不完整');
  return Buffer.concat(parts);
}

module.exports = {withPngAuthor};
