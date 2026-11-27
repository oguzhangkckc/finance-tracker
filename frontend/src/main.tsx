import "@mantine/core/styles.css";
import "@mantine/charts/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { App } from "./App";
import { createApi } from "./api/client";
import { createQueryClient } from "./api/queries";
import { routes } from "./routes";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html'de #root yok.");
}

createRoot(container).render(
  <StrictMode>
    <App api={createApi()} queryClient={createQueryClient()} router={createBrowserRouter(routes)} />
  </StrictMode>,
);
