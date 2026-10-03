/**
 * Минимальный WebSocket-клиент для Chrome DevTools Protocol.
 *
 * Своя реализация вместо пакета `ws`: скрипту нужны только текстовые
 * кадры и маскирование исходящих, а лишняя зависимость в дереве
 * монорепозитория — это ещё одна лицензия на проверку по ТЗ п.7.1.6.
 *
 * Реализовано ровно то, что требуется CDP:
 *   - приём текстовых кадров без маски (так шлёт сервер);
 *   - отправка с маской (так требует протокол от клиента);
 *   - обработка ping/pong и закрытия.
 *
 * Формат кадра: RFC 6455, только opcode 1 (text), без продолжений —
 * CDP укладывается в пределах одного кадра.
 */

import { createConnection } from 'node:net';
import { createHash, randomBytes } from 'node:crypto';
import { EventEmitter } from 'node:events';

const GUID = '258EAFA5-E914-47DA-95CA-5AB0DC85B11D';

const OP_CONT = 0x0;
const OP_TEXT = 0x1;
const OP_BIN = 0x2;
const OP_CLOSE = 0x8;
const OP_PING = 0x9;
const OP_PONG = 0xa;

export class MiniWebSocket extends EventEmitter {
  /**
   * @param {string} url ws://host:port/path
   */
  constructor(url) {
    super();
    this.url = new URL(url);
    this.host = this.url.hostname;
    this.port = Number(this.url.port || 80);
    this.key = randomBytes(16).toString('base64');
    this.buffer = Buffer.alloc(0);
    this.ready = false;
    this.closed = false;
    /** Очередь кадров, пришедших до завершения рукопожатия. */
    this.pending = [];
  }

  connect() {
    return new Promise((resolve, reject) => {
      const req =
        `GET ${this.url.pathname}${this.url.search} HTTP/1.1\r\n` +
        `Host: ${this.host}:${this.port}\r\n` +
        'Upgrade: websocket\r\n' +
        'Connection: Upgrade\r\n' +
        `Sec-WebSocket-Key: ${this.key}\r\n` +
        'Sec-WebSocket-Version: 13\r\n\r\n';

      this.socket = createConnection({ host: this.host, port: this.port }, () => {
        this.socket.write(req);
      });

      this.socket.on('data', (chunk) => {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        this.#onData();
      });

      this.socket.on('error', (e) => {
        // После штатного закрытия браузера сокет отдаёт ECONNRESET.
        // Бросать это вверх нельзя: скрипт к этому моменту уже всё
        // измерил, и падение из-за уборки процессов бессмысленно.
        if (this.closed || this.ready) return;
        if (!this.ready) reject(e);
        this.emit('error', e);
      });

      this.socket.on('close', () => {
        this.closed = true;
        this.emit('close');
      });

      this.once('open', resolve);
    });
  }

  /** Парсит накопленные байты: сначала рукопожатие, потом кадры. */
  #onData() {
    if (!this.ready) {
      const end = this.buffer.indexOf('\r\n\r\n');
      if (end === -1) return;
      const head = this.buffer.subarray(0, end).toString('ascii');
      if (!head.startsWith('HTTP/1.1 101')) {
        this.emit('error', new Error(`рукопожатие не удалось: ${head.split('\r\n')[0]}`));
        return;
      }
      this.buffer = this.buffer.subarray(end + 4);
      this.ready = true;
      this.emit('open');
      for (const frame of this.pending) this.emit('message', frame);
      this.pending = [];
    }
    this.#readFrames();
  }

  #readFrames() {
    for (;;) {
      const buf = this.buffer;
      if (buf.length < 2) return;

      const b0 = buf[0];
      const b1 = buf[1];
      const opcode = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let len = b1 & 0x7f;
      let off = 2;

      if (len === 126) {
        if (buf.length < off + 2) return;
        len = buf.readUInt16BE(off);
        off += 2;
      } else if (len === 127) {
        if (buf.length < off + 8) return;
        // CDP не передаёт кадры длиннее 4 ГБ; старшие байты игнорируем.
        len = buf.readUInt32BE(off + 4);
        off += 8;
      }

      let mask = null;
      if (masked) {
        if (buf.length < off + 4) return;
        mask = buf.subarray(off, off + 4);
        off += 4;
      }

      if (buf.length < off + len) return;

      let payload = Buffer.from(buf.subarray(off, off + len));
      if (mask) {
        for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
      }
      this.buffer = buf.subarray(off + len);

      if (opcode === OP_CLOSE) {
        this.closed = true;
        this.socket.end();
        this.emit('close');
        return;
      }
      if (opcode === OP_PING) {
        this.#send(OP_PONG, payload);
        continue;
      }
      if (opcode === OP_PONG) continue;
      if (opcode === OP_CONT) continue;

      const text = payload.toString('utf8');
      if (opcode === OP_TEXT || opcode === OP_BIN) {
        if (this.ready) this.emit('message', text);
        else this.pending.push(text);
      }
    }
  }

  #send(opcode, payload) {
    const data = Buffer.isBuffer(payload) ? payload : Buffer.from(payload, 'utf8');
    const mask = randomBytes(4);
    const masked = Buffer.alloc(data.length);
    for (let i = 0; i < data.length; i++) masked[i] = data[i] ^ mask[i % 4];

    let header;
    if (data.length < 126) {
      header = Buffer.from([0x80 | opcode, 0x80 | data.length]);
    } else if (data.length < 65536) {
      header = Buffer.alloc(4);
      header[0] = 0x80 | opcode;
      header[1] = 0x80 | 126;
      header.writeUInt16BE(data.length, 2);
    } else {
      header = Buffer.alloc(10);
      header[0] = 0x80 | opcode;
      header[1] = 0x80 | 127;
      header.writeUInt32BE(0, 2);
      header.writeUInt32BE(data.length, 6);
    }
    this.socket.write(Buffer.concat([header, mask, masked]));
  }

  send(text) {
    if (this.closed) throw new Error('сокет закрыт');
    this.#send(OP_TEXT, text);
  }

  close() {
    try {
      this.#send(OP_CLOSE, Buffer.alloc(0));
      this.socket.end();
    } catch {
      this.socket?.destroy();
    }
  }
}

/** Проверка ожидаемого accept-key по RFC 6455. */
export function expectedAccept(key) {
  return createHash('sha1').update(key + GUID).digest('base64');
}
