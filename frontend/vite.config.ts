import react from "@vitejs/plugin-react";
import { loadEnv, type ProxyOptions } from "vite";
import { defineConfig } from "vitest/config";

// Yerel geliştirmede Access yoktur (K-139): scripts/yerel_api.py jetonu .env.local'a yazar;
// vekil onu /api isteklerine ekler ve kökeni API'nin beklediğine çevirir. Jeton yoksa vekil yok.
function localApi(mode: string): Record<string, ProxyOptions> | undefined {
  const env = loadEnv(mode, ".", "FT_YEREL_");
  const token = env.FT_YEREL_JETON;
  if (token === undefined || token === "") {
    return undefined;
  }
  return {
    "/api": {
      target: env.FT_YEREL_API ?? "http://127.0.0.1:8765",
      headers: { "Cf-Access-Jwt-Assertion": token, Origin: env.FT_YEREL_KOKEN ?? "" },
    },
  };
}

export default defineConfig(({ mode }) => {
  const proxy = localApi(mode);
  return {
    plugins: [react()],
    server: { proxy },
    preview: { proxy },
    build: {
      outDir: "dist",
      sourcemap: false,
      rolldownOptions: {
        output: {
          // Kütüphaneler uygulama kodundan ayrı parçada; sürüm değişmedikçe önbellekte kalır.
          // Grafik paketleri burada değil, onları kullanan sayfanın parçasında yüklenir.
          codeSplitting: {
            groups: [
              {
                name: "react",
                test: /node_modules[\\/](react|react-dom|react-router|scheduler|@tanstack)[\\/]/,
              },
              {
                name: "mantine",
                test: /node_modules[\\/]@mantine[\\/](core|hooks|notifications)[\\/]/,
              },
            ],
          },
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
      testTimeout: 15_000,
    },
  };
});
