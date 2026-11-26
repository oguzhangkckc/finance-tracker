import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// Sayfalar tembel yüklenir; grafikli sayfanın ilk dönüştürülmesi soğuk önbellekte bir saniyeyi aşabilir.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  window.localStorage.clear();
});

// Mantine jsdom'da bulunmayan tarayıcı API'lerini kullanır.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = ResizeObserverStub;
Element.prototype.scrollIntoView = () => undefined;
// jsdom düzen hesaplamaz; Recharts ölçemediği grafiği çizmez ve uyarı yazar.
Element.prototype.getBoundingClientRect = () => DOMRect.fromRect({ width: 800, height: 300 });
