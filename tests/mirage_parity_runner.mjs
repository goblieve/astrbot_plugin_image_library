import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const testDir = dirname(fileURLToPath(import.meta.url));
const fixturePath = process.argv[2] || resolve(testDir, "fixtures/mirage-parity.json");
const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
const modulePath = resolve(testDir, "../views/gallery/mirage.js");
const source = await readFile(modulePath, "utf8");
globalThis.ImageData = class ImageData {
  constructor(data, width, height) {
    this.data = data;
    this.width = width;
    this.height = height;
  }
};
const mirage = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));

function rgbaData(rgbPixels) {
  return new Uint8ClampedArray(rgbPixels.flatMap((pixel) => [...pixel, 255]));
}

function composite(rgba, background) {
  const result = new Uint8ClampedArray(rgba.length / 4 * 3);
  for (let pixel = 0, src = 0, dst = 0; src < rgba.length; pixel += 1, src += 4, dst += 3) {
    const alpha = rgba[src + 3] / 255;
    for (let channel = 0; channel < 3; channel += 1) {
      result[dst + channel] =
        rgba[src + channel] * alpha + background * (1 - alpha);
    }
  }
  return Array.from(result);
}

const output = {};
for (const item of fixture.cases) {
  const inner = { width: item.width, height: item.height, data: rgbaData(item.inner) };
  const cover = { width: item.width, height: item.height, data: rgbaData(item.cover) };
  const result = mirage.processMiragePixels(inner, cover, item.options);
  const rgba = Array.from(result.data);
  output[item.name] = {
    rgba,
    white: composite(result.data, 255),
    black: composite(result.data, 0),
  };
}
process.stdout.write(JSON.stringify(output));