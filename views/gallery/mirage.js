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

function grayscaleByte(red, green, blue) {
  // Match Pillow's RGB -> L fixed-point coefficients so server exports and
  // browser previews use the same quantized luminance for alpha calculation.
  return (red * 19595 + green * 38470 + blue * 7471 + 32768) >> 16;
}

export function prepareMiragePixelBuffers(width, height, innerData, coverData) {
  const expectedLength = Number(width) * Number(height) * 4;
  if (
    !Number.isInteger(width)
    || !Number.isInteger(height)
    || width < 1
    || height < 1
    || innerData.length !== expectedLength
    || coverData.length !== expectedLength
  ) {
    throw new Error("里图和表图像素数据尺寸无效。");
  }

  const innerBytes = innerData instanceof Uint8ClampedArray
    ? innerData
    : new Uint8ClampedArray(innerData);
  const coverBytes = coverData instanceof Uint8ClampedArray
    ? coverData
    : new Uint8ClampedArray(coverData);
  const pixelCount = width * height;
  const innerGray = new Uint8ClampedArray(pixelCount);
  const coverGray = new Uint8ClampedArray(pixelCount);
  for (let pixel = 0, offset = 0; pixel < pixelCount; pixel += 1, offset += 4) {
    innerGray[pixel] = grayscaleByte(
      innerBytes[offset], innerBytes[offset + 1], innerBytes[offset + 2],
    );
    coverGray[pixel] = grayscaleByte(
      coverBytes[offset], coverBytes[offset + 1], coverBytes[offset + 2],
    );
  }
  return {
    width,
    height,
    innerData: innerBytes,
    coverData: coverBytes,
    innerGray,
    coverGray,
  };
}

export function prepareMiragePixels(innerImageData, coverImageData) {
  if (
    innerImageData.width !== coverImageData.width
    || innerImageData.height !== coverImageData.height
  ) {
    throw new Error("里图和表图尺寸不一致。");
  }
  return prepareMiragePixelBuffers(
    innerImageData.width,
    innerImageData.height,
    innerImageData.data,
    coverImageData.data,
  );
}

export function processPreparedMiragePixels(prepared, options = {}) {
  const {
    width, height, innerData, coverData, innerGray, coverGray,
  } = prepared;
  const output = new Uint8ClampedArray(innerData.length);
  const scaleInner = clamp01(options.scaleInner);
  const scaleCover = 1 - clamp01(options.scaleCover);
  const desatInner = clamp01(options.desatInner);
  const desatCover = clamp01(options.desatCover);
  const weightInner = clamp01(options.weightInner);
  const colored = options.colored !== false;

  for (let pixel = 0, offset = 0; pixel < innerGray.length; pixel += 1, offset += 4) {
    const innerLuminance = innerGray[pixel] * scaleInner;
    const coverLuminance = 255 - (255 - coverGray[pixel]) * scaleCover;
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

export function processMiragePixels(innerImageData, coverImageData, options = {}) {
  const prepared = prepareMiragePixels(innerImageData, coverImageData);
  return processPreparedMiragePixels(prepared, options);
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

export function prepareMirageSources(innerImage, coverImage, maxSize = 1200) {
  if (!innerImage?.naturalWidth || !coverImage?.naturalWidth) {
    throw new Error("请先载入里图和表图。");
  }
  maxSize = Math.max(240, Math.min(1200, Math.round(Number(maxSize) || 1200)));
  let width;
  let height;
  if (coverImage.naturalWidth > coverImage.naturalHeight) {
    width = maxSize;
    height = Math.max(1, Math.ceil(coverImage.naturalHeight * maxSize / coverImage.naturalWidth));
  } else {
    height = maxSize;
    width = Math.max(1, Math.ceil(coverImage.naturalWidth * maxSize / coverImage.naturalHeight));
  }

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
  return {
    width,
    height,
    innerData: innerData.data,
    coverData: coverData.data,
  };
}

export function renderMirage(innerImage, coverImage, options = {}) {
  const maxSize = Math.max(240, Math.min(1200, Math.round(Number(options.maxSize) || 1200)));
  const sources = prepareMirageSources(innerImage, coverImage, maxSize);
  const prepared = prepareMiragePixelBuffers(
    sources.width,
    sources.height,
    sources.innerData,
    sources.coverData,
  );
  return processPreparedMiragePixels(prepared, options);
}
