import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
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
});
