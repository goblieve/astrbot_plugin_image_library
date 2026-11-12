import {
  prepareMiragePixelBuffers,
  processPreparedMiragePixels,
} from "./mirage.js";

let prepared = null;

self.addEventListener("message", (event) => {
  const { requestId, type } = event.data || {};
  try {
    if (type === "prepare") {
      prepared = prepareMiragePixelBuffers(
        Number(event.data.width),
        Number(event.data.height),
        new Uint8ClampedArray(event.data.innerBuffer),
        new Uint8ClampedArray(event.data.coverBuffer),
      );
      self.postMessage({ requestId, ok: true, type: "prepared" });
      return;
    }
    if (type === "render") {
      if (!prepared) throw new Error("预览像素尚未载入。");
      const imageData = processPreparedMiragePixels(
        prepared,
        event.data.options || {},
      );
      const pixels = imageData.data;
      self.postMessage(
        {
          requestId,
          ok: true,
          type: "rendered",
          width: imageData.width,
          height: imageData.height,
          pixelBuffer: pixels.buffer,
        },
        [pixels.buffer],
      );
      return;
    }
    throw new Error("未知的幻影坦克像素任务。");
  } catch (error) {
    self.postMessage({
      requestId,
      ok: false,
      error: error?.message || "幻影坦克预览计算失败。",
    });
  }
});
