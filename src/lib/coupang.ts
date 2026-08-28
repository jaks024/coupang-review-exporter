const PRODUCT_PATH = /\/products\/(\d+)/;

export type ParsedProduct = {
  productId: string;
  normalizedUrl: string;
};

export function parseCoupangProduct(value: string): ParsedProduct {
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) {
    return {
      productId: trimmed,
      normalizedUrl: `https://www.coupang.com/vp/products/${trimmed}`,
    };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error("Paste a complete Coupang product URL.");
  }

  const hostname = parsed.hostname.toLowerCase();
  if (hostname !== "coupang.com" && !hostname.endsWith(".coupang.com")) {
    throw new Error("The URL must be on coupang.com.");
  }

  const match = parsed.pathname.match(PRODUCT_PATH);
  if (!match) {
    throw new Error("The URL must contain /products/<productId>.");
  }

  return { productId: match[1], normalizedUrl: parsed.toString() };
}

export function downloadFilename(contentDisposition: string | null, productId: string): string {
  const match = contentDisposition?.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? `coupang-reviews-${productId}.csv`;
}

