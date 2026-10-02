/**
 * Минимальный декодер PNG.
 *
 * Нужен для автоматической проверки скриншотов: getImageData из контекста
 * Konva отдаёт буфер, который не совпадает с тем, что видно на экране,
 * и проверка «холст не чёрный» давала ложную тревогу. Надёжный источник
 * — пиксели самого PNG, снятого браузером.
 *
 * Поддерживает 8 бит на канал, типы 2 (RGB) и 6 (RGBA) — этого хватает
 * для снимков Chrome.
 */

import { inflateSync } from 'node:zlib';

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/**
 * @param {Buffer} buf данные PNG
 * @returns {{ width: number, height: number, pixels: Buffer }} RGBA-пиксели
 */
export function decodePng(buf) {
  if (!buf.subarray(0, 8).equals(SIGNATURE)) {
    throw new Error('не PNG: сигнатура не совпала');
  }

  let offset = 8;
  let header = null;
  const idat = [];

  while (offset < buf.length) {
    const length = buf.readUInt32BE(offset);
    const type = buf.toString('ascii', offset + 4, offset + 8);
    const data = buf.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length; // длина + тип + данные + CRC

    if (type === 'IHDR') {
      header = {
        width: data.readUInt32BE(0),
        height: data.readUInt32BE(4),
        bitDepth: data[8],
        colorType: data[9],
        interlace: data[12],
      };
    } else if (type === 'IDAT') {
      idat.push(data);
    } else if (type === 'IEND') {
      break;
    }
  }

  if (!header) throw new Error('PNG без IHDR');
  if (header.bitDepth !== 8) throw new Error(`глубина ${header.bitDepth} не поддерживается`);
  if (header.interlace !== 0) throw new Error('чересстрочная развёртка не поддерживается');
  if (header.colorType !== 2 && header.colorType !== 6) {
    throw new Error(`тип цвета ${header.colorType} не поддерживается`);
  }

  const channels = header.colorType === 6 ? 4 : 3;
  const { width, height } = header;
  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const out = Buffer.alloc(width * height * 4);

  // Развёртка фильтров PNG: каждая строка хранит разницу с предыдущей.
  let prev = Buffer.alloc(stride);
  let pos = 0;

  for (let y = 0; y < height; y++) {
    const filter = raw[pos++];
    const line = Buffer.from(raw.subarray(pos, pos + stride));
    pos += stride;

    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? line[x - channels] : 0;
      const b = prev[x];
      const c = x >= channels ? prev[x - channels] : 0;
      switch (filter) {
        case 0:
          break;
        case 1:
          line[x] = (line[x] + a) & 0xff;
          break;
        case 2:
          line[x] = (line[x] + b) & 0xff;
          break;
        case 3:
          line[x] = (line[x] + ((a + b) >> 1)) & 0xff;
          break;
        case 4: {
          const p = a + b - c;
          const pa = Math.abs(p - a);
          const pb = Math.abs(p - b);
          const pc = Math.abs(p - c);
          const pred = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
          line[x] = (line[x] + pred) & 0xff;
          break;
        }
        default:
          throw new Error(`неизвестный фильтр ${filter}`);
      }
    }

    for (let x = 0; x < width; x++) {
      const s = x * channels;
      const d = (y * width + x) * 4;
      out[d] = line[s];
      out[d + 1] = line[s + 1];
      out[d + 2] = line[s + 2];
      out[d + 3] = channels === 4 ? line[s + 3] : 255;
    }
    prev = line;
  }

  return { width, height, pixels: out };
}

/**
 * Собирает статистику по прямоугольной области изображения.
 * @returns {{ distinct: number, blackShare: number, mean: number[] }}
 */
export function regionStats(img, box) {
  const x0 = Math.max(0, Math.round(box.x));
  const y0 = Math.max(0, Math.round(box.y));
  const x1 = Math.min(img.width, Math.round(box.x + box.width));
  const y1 = Math.min(img.height, Math.round(box.y + box.height));

  const seen = new Set();
  let black = 0;
  let total = 0;
  const sum = [0, 0, 0];

  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const i = (y * img.width + x) * 4;
      const r = img.pixels[i];
      const g = img.pixels[i + 1];
      const b = img.pixels[i + 2];
      // Квантование до 4 бит: сглаживание теней не должно давать
      // тысячу «разных» цветов на ровной заливке.
      seen.add(((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4));
      if (r < 14 && g < 14 && b < 14) black++;
      sum[0] += r;
      sum[1] += g;
      sum[2] += b;
      total++;
    }
  }

  return {
    distinct: seen.size,
    blackShare: total ? black / total : 0,
    mean: sum.map((s) => Math.round(s / (total || 1))),
  };
}
