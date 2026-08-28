import { describe, expect, it } from "vitest";
import { downloadFilename, parseCoupangProduct } from "./coupang";

describe("parseCoupangProduct", () => {
  it("extracts a product ID from a full product URL", () => {
    const result = parseCoupangProduct(
      "https://www.coupang.com/vp/products/1920045216?itemId=3260034071&vendorItemId=71284447167",
    );

    expect(result.productId).toBe("1920045216");
  });

  it("accepts a numeric product ID", () => {
    expect(parseCoupangProduct("1920045216").normalizedUrl).toBe(
      "https://www.coupang.com/vp/products/1920045216",
    );
  });

  it("rejects a non-Coupang URL", () => {
    expect(() => parseCoupangProduct("https://example.com/products/1920045216")).toThrow(
      "coupang.com",
    );
  });
});

describe("downloadFilename", () => {
  it("uses the filename returned by the API", () => {
    expect(
      downloadFilename('attachment; filename="reviews.csv"', "1920045216"),
    ).toBe("reviews.csv");
  });
});

