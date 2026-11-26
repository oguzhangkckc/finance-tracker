import { Button, Container, MantineProvider, Stack, Text, Title } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { lazy } from "react";
import { Outlet, type RouteObject, useMatch, useParams } from "react-router";
import { Shell } from "./layout/Shell";
import { MorePage } from "./pages/MorePage";
import { NotFound } from "./pages/NotFound";
import { OpenDefaultProfile } from "./pages/OpenDefaultProfile";
import { isProfileSlug } from "./profile";
import { cssVariablesResolver, THEMES } from "./theme";

// Grafik kütüphanesi yalnız onu kullanan sayfanın parçasına girer.
const OverviewPage = lazy(() =>
  import("./pages/OverviewPage").then((module) => ({ default: module.OverviewPage })),
);
const AllocationPage = lazy(() =>
  import("./pages/AllocationPage").then((module) => ({ default: module.AllocationPage })),
);
const ReturnsPage = lazy(() =>
  import("./pages/ReturnsPage").then((module) => ({ default: module.ReturnsPage })),
);
const ReportsPage = lazy(() =>
  import("./pages/ReportsPage").then((module) => ({ default: module.ReportsPage })),
);
const ReportPage = lazy(() =>
  import("./pages/ReportsPage").then((module) => ({ default: module.ReportPage })),
);
const HoldingsPage = lazy(() =>
  import("./pages/HoldingsPage").then((module) => ({ default: module.HoldingsPage })),
);
const LotsPage = lazy(() =>
  import("./pages/HoldingsPage").then((module) => ({ default: module.LotsPage })),
);
const TransactionsPage = lazy(() =>
  import("./pages/TransactionsPage").then((module) => ({ default: module.TransactionsPage })),
);
const AlertsPage = lazy(() =>
  import("./pages/AlertsPage").then((module) => ({ default: module.AlertsPage })),
);
const SystemPage = lazy(() =>
  import("./pages/SystemPage").then((module) => ({ default: module.SystemPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })),
);

function Root() {
  const candidate = useMatch("/:profil/*")?.params.profil;
  const profile = isProfileSlug(candidate) ? candidate : "gercek";
  return (
    <MantineProvider
      theme={THEMES[profile]}
      cssVariablesResolver={cssVariablesResolver}
      defaultColorScheme="auto"
    >
      <Notifications />
      <Outlet />
    </MantineProvider>
  );
}

function ProfileRoute() {
  const { profil } = useParams();
  if (!isProfileSlug(profil)) {
    return <Standalone />;
  }
  return <Shell profile={profil} />;
}

function Standalone() {
  return (
    <Container size="sm" py="xl">
      <NotFound />
    </Container>
  );
}

function RouteError() {
  return (
    <Container size="sm" py="xl">
      <Stack gap="md" align="flex-start">
        <title>Hata · finans-takip</title>
        <Title order={1}>Beklenmeyen bir hata oluştu</Title>
        <Text>Sayfayı yenilemek çoğu zaman yeter; sürerse Sistem sayfasına bak.</Text>
        <Button onClick={() => window.location.reload()}>Sayfayı yenile</Button>
      </Stack>
    </Container>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Root />,
    children: [
      {
        errorElement: <RouteError />,
        children: [
          { index: true, element: <OpenDefaultProfile /> },
          {
            path: ":profil",
            element: <ProfileRoute />,
            children: [
              { index: true, element: <OverviewPage /> },
              { path: "varliklar", element: <HoldingsPage /> },
              { path: "varliklar/lotlar", element: <LotsPage /> },
              { path: "islemler", element: <TransactionsPage /> },
              { path: "dagilim", element: <AllocationPage /> },
              { path: "getiri", element: <ReturnsPage /> },
              { path: "raporlar", element: <ReportsPage /> },
              { path: "raporlar/:tur", element: <ReportPage /> },
              { path: "alarmlar", element: <AlertsPage /> },
              { path: "ayarlar", element: <SettingsPage /> },
              { path: "sistem", element: <SystemPage /> },
              { path: "daha", element: <MorePage /> },
              { path: "*", element: <NotFound /> },
            ],
          },
          { path: "*", element: <Standalone /> },
        ],
      },
    ],
  },
];
