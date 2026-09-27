// Previews are opaque PNGs on white; clearing only the white connected to the image border
// keeps white bricks white, since edge lines separate their faces from the background.
const MAX_WIDTH = 400;
const WHITE = 236;
const FRINGE = 160;

function clearBackground(data, width, height) {
  const count = width * height;
  const cleared = new Uint8Array(count);
  const stack = new Int32Array(count);
  let top = 0;
  const isWhite = i => data[i * 4] >= WHITE && data[i * 4 + 1] >= WHITE && data[i * 4 + 2] >= WHITE;
  const push = i => {
    if (!cleared[i] && isWhite(i)) { cleared[i] = 1; stack[top++] = i; }
  };
  for (let x = 0; x < width; x++) { push(x); push(count - width + x); }
  for (let y = 0; y < height; y++) { push(y * width); push(y * width + width - 1); }
  while (top) {
    const i = stack[--top];
    const x = i % width;
    if (x > 0) push(i - 1);
    if (x < width - 1) push(i + 1);
    if (i >= width) push(i - width);
    if (i < count - width) push(i + width);
  }
  for (let i = 0; i < count; i++) {
    if (cleared[i]) { data[i * 4 + 3] = 0; continue; }
    const x = i % width;
    const edge = (x > 0 && cleared[i - 1]) || (x < width - 1 && cleared[i + 1])
      || (i >= width && cleared[i - width]) || (i < count - width && cleared[i + width]);
    if (!edge) continue;
    const p = i * 4;
    const low = Math.min(data[p], data[p + 1], data[p + 2]);
    if (low <= FRINGE) continue;
    // Anti-aliased pixel blended with the white matte: recover its alpha and un-blend the color.
    const alpha = Math.max((255 - low) / (255 - FRINGE), 0.05);
    for (let c = 0; c < 3; c++) data[p + c] = Math.max(0, Math.round((data[p + c] - 255 * (1 - alpha)) / alpha));
    data[p + 3] = Math.round(alpha * 255);
  }
}

// Draws straight into the visible canvas: encoding to a PNG blob costs ~1 s per image in Chrome.
export function cutOutBackground(img, canvas) {
  const scale = Math.min(1, MAX_WIDTH / img.naturalWidth);
  const width = Math.max(1, Math.round(img.naturalWidth * scale));
  const height = Math.max(1, Math.round(img.naturalHeight * scale));
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(img, 0, 0, width, height);
  const image = context.getImageData(0, 0, width, height);
  clearBackground(image.data, width, height);
  context.putImageData(image, 0, 0);
}
