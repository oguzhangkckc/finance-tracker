import { AppShell, Button, Group, NavLink, Text, UnstyledButton } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useLocation } from "react-router";
import { useApi } from "../api/context";
import { sessionQuery } from "../api/queries";
import { PROFILE_LABELS, PROFILES, type ProfileSlug, SANAL_NOTICE } from "../profile";
import { Icon } from "./icons";
import { href, isCurrent, isTabCurrent, NAV, subpath, TABS } from "./nav";

const BAR = 56;
const BAND = 32;

function currentPage(active: boolean): "page" | undefined {
  return active ? "page" : undefined;
}

export function Shell({ profile }: { profile: ProfileSlug }) {
  const { pathname } = useLocation();
  const rest = subpath(pathname, profile);
  const session = useQuery(sessionQuery(useApi()));
  const sanal = profile === "sanal";

  return (
    <>
      <a className="ft-skip" href="#icerik">
        İçeriğe geç
      </a>
      <AppShell
        header={{ height: sanal ? BAR + BAND : BAR }}
        navbar={{ width: 232, breakpoint: "sm", collapsed: { mobile: true } }}
        footer={{ height: { base: 64, sm: 0 } }}
        padding="md"
      >
        <AppShell.Header>
          {sanal && (
            <div className="ft-band" role="status">
              {SANAL_NOTICE}
            </div>
          )}
          <Group h={BAR} px="md" justify="space-between" wrap="nowrap">
            <Text fw={700}>
              finans-takip{" "}
              <Text span c="dimmed" fw={400}>
                · {PROFILE_LABELS[profile]}
              </Text>
            </Text>
            <Group gap="md" wrap="nowrap">
              <nav aria-label="Portföy">
                <Group gap={4} wrap="nowrap">
                  {PROFILES.map((other) => (
                    <Button
                      key={other}
                      component={Link}
                      to={href(other, rest)}
                      size="compact-md"
                      variant={other === profile ? "filled" : "subtle"}
                      aria-current={currentPage(other === profile)}
                    >
                      {PROFILE_LABELS[other]}
                    </Button>
                  ))}
                </Group>
              </nav>
              {session.data && (
                <Text size="sm" c="dimmed" visibleFrom="sm">
                  {session.data.email}
                </Text>
              )}
            </Group>
          </Group>
        </AppShell.Header>
        <AppShell.Navbar p="sm" aria-label="Sayfalar">
          {NAV.map((item) => {
            const active = isCurrent(item.path, rest);
            return (
              <NavLink
                key={item.path}
                component={Link}
                to={href(profile, item.path)}
                label={item.label}
                leftSection={<Icon name={item.icon} />}
                active={active}
                aria-current={currentPage(active)}
                className="ft-nav"
              />
            );
          })}
        </AppShell.Navbar>
        <AppShell.Main id="icerik" tabIndex={-1}>
          <Outlet />
        </AppShell.Main>
        <AppShell.Footer hiddenFrom="sm">
          <nav aria-label="Sayfalar (kısa)" className="ft-tabs">
            {TABS.map((tab) => {
              const active = isTabCurrent(tab.path, rest);
              return (
                <UnstyledButton
                  key={tab.path}
                  component={Link}
                  to={href(profile, tab.path)}
                  className="ft-tab"
                  data-active={active || undefined}
                  aria-current={currentPage(active)}
                >
                  <Icon name={tab.icon} size={22} />
                  <span>{tab.label}</span>
                </UnstyledButton>
              );
            })}
          </nav>
        </AppShell.Footer>
      </AppShell>
    </>
  );
}
