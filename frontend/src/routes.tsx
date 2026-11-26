import { Button, Container, MantineProvider, Stack, Text, Title } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { Outlet, type RouteObject, useMatch, useParams } from "react-router";
import { Shell } from "./layout/Shell";
import { MorePage } from "./pages/MorePage";
import { NotFound } from "./pages/NotFound";
import { OpenDefaultProfile } from "./pages/OpenDefaultProfile";
import { Page } from "./pages/Page";
import { isProfileSlug } from "./profile";
import { cssVariablesResolver, THEMES } from "./theme";

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
              { index: true, element: <Page title="Özet" /> },
              { path: "varliklar", element: <Page title="Varlıklar" /> },
              { path: "varliklar/lotlar", element: <Page title="Lotlar" /> },
              { path: "islemler", element: <Page title="İşlemler" /> },
              { path: "dagilim", element: <Page title="Dağılım" /> },
              { path: "getiri", element: <Page title="Getiri" /> },
              { path: "raporlar", element: <Page title="Raporlar" /> },
              { path: "alarmlar", element: <Page title="Alarmlar" /> },
              { path: "ayarlar", element: <Page title="Ayarlar" /> },
              { path: "sistem", element: <Page title="Sistem" /> },
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
