/*
 * Independently implemented pixel-processing port based on the algorithm in
 * Mirage_Colored: https://github.com/TankFactory/Mirage_Colored
 * Attribution and the MIT license are recorded in THIRD_PARTY_NOTICES.md.
 */

const clamp01 = (value) => Math.min(1, Math.max(0, Number(value) || 0));

function clampByte(value) {
  if (!Number.isFinite(value) || value <= 0) return 0;
  if (value >= 255) return 255;
  const floor = Math.floor(value);
  const fraction = value - floor;
  return fraction > 0.5 || (fraction === 0.5 && (floor & 1) === 1)
    ? floor + 1
    : floor;
}

/**
 * Combine aligned ImageData into a transparent phantom-tank image.
 * This single-pass implementation keeps the same clamped intermediate values
 * while avoiding several full-size temporary pixel buffers.
 */
export function processMiragePixels(innerImageData, coverImageData, options = {}) {
  if (
    innerImageData.width !== coverImageData.width
    || innerImageData.height !== coverImageData.height
  ) {
    throw new Error("里图和表图尺寸不一致。");
  }

  const width = innerImageData.width;
  const height = innerImageData.height;
  const innerData = innerImageData.data;
  const coverData = coverImageData.data;
  const output = new Uint8ClampedArray(innerData.length);
  const scaleInner = clamp01(options.scaleInner);
  const scaleCover = 1 - clamp01(options.scaleCover);
  const desatInner = clamp01(options.desatInner);
  const desatCover = clamp01(options.desatCover);
  const weightInner = clamp01(options.weightInner);
  const colored = options.colored !== false;

  for (let offset = 0; offset < output.length; offset += 4) {
    const innerRed = innerData[offset];
    const innerGreen = innerData[offset + 1];
    const innerBlue = innerData[offset + 2];
    const coverRed = coverData[offset];
    const coverGreen = coverData[offset + 1];
    const coverBlue = coverData[offset + 2];
    const innerGray = clampByte(0.299 * innerRed + 0.587 * innerGreen + 0.114 * innerBlue);
    const coverGray = clampByte(0.299 * coverRed + 0.587 * coverGreen + 0.114 * coverBlue);
    const innerLuminance = innerGray * scaleInner;
    const coverLuminance = 255 - (255 - coverGray) * scaleCover;
    const alphaByte = Math.min(
      255,
      Math.max(255 + innerLuminance - coverLuminance, 0),
    );

    if (alphaByte <= 0) {
      output[offset] = 0;
      output[offset + 1] = 0;
      output[offset + 2] = 0;
      output[offset + 3] = 0;
      continue;
    }

    if (!colored) {
      const luminance = innerLuminance * 255 / alphaByte;
      output[offset] = luminance;
      output[offset + 1] = luminance;
      output[offset + 2] = luminance;
      output[offset + 3] = alphaByte;
      continue;
    }

    for (let channel = 0; channel < 3; channel += 1) {
      const originalInner = innerData[offset + channel] * scaleInner;
      const preparedInner = clampByte(
        originalInner + (innerLuminance - originalInner) * desatInner,
      );
      const originalCover = 255 - (255 - coverData[offset + channel]) * scaleCover;
      const preparedCover = clampByte(
        originalCover + (coverLuminance - originalCover) * desatCover,
      );
      output[offset + channel] = (
        (preparedInner - alphaByte + 255 - preparedCover) * weightInner
          + alphaByte - 255 + preparedCover
      ) / (alphaByte / 255);
    }
    output[offset + 3] = alphaByte;
  }

  return new ImageData(output, width, height);
}

function canvasFor(image, width, height, draw) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("浏览器无法创建图片处理画布。");
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  draw(context, image);
  return context.getImageData(0, 0, width, height);
}

/** Resize the inner image, center-crop the cover image, then process both pixel buffers. */
export function renderMirage(innerImage, coverImage, options = {}) {
  if (!innerImage?.naturalWidth || !coverImage?.naturalWidth) {
    throw new Error("请先载入里图和表图。");
  }
  const maxSize = Math.max(240, Math.min(1200, Math.round(Number(options.maxSize) || 1200)));
  let width;
  let height;
  if (coverImage.naturalWidth > coverImage.naturalHeight) {
    width = maxSize;
    height = Math.max(1, Math.ceil(coverImage.naturalHeight * maxSize / coverImage.naturalWidth));
  } else {
    height = maxSize;
    width = Math.max(1, Math.ceil(coverImage.naturalWidth * maxSize / coverImage.naturalHeight));
  }

  // The inner image is revealed on black, while the cover image is revealed on white.
  const innerData = canvasFor(innerImage, width, height, (context, image) => {
    const sourceRatio = image.naturalWidth / image.naturalHeight;
    const targetRatio = width / height;
    let sx = 0;
    let sy = 0;
    let sw = image.naturalWidth;
    let sh = image.naturalHeight;
    if (sourceRatio < targetRatio) {
      sh = image.naturalWidth / targetRatio;
      sy = (image.naturalHeight - sh) / 2;
    } else {
      sw = image.naturalHeight * targetRatio;
      sx = (image.naturalWidth - sw) / 2;
    }
    context.drawImage(image, sx, sy, sw, sh, 0, 0, width, height);
  });
  const coverData = canvasFor(coverImage, width, height, (context, image) => {
    context.drawImage(image, 0, 0, width, height);
  });
  return processMiragePixels(innerData, coverData, options);
}