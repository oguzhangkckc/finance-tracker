import { NavLink, Stack } from "@mantine/core";
import { Link } from "react-router";
import { Icon } from "../layout/icons";
import { href, MORE } from "../layout/nav";
import { useProfile } from "../profile";
import { Page } from "./Page";

export function MorePage() {
  const profile = useProfile();
  return (
    <Page title="Daha fazla">
      <nav aria-label="Diğer sayfalar">
        <Stack gap={4}>
          {MORE.map((item) => (
            <NavLink
              key={item.path}
              component={Link}
              to={href(profile, item.path)}
              label={item.label}
              leftSection={<Icon name={item.icon} />}
              className="ft-nav"
            />
          ))}
        </Stack>
      </nav>
    </Page>
  );
}
