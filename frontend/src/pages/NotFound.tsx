import { Anchor, Stack, Text, Title } from "@mantine/core";
import { Link, useParams } from "react-router";
import { href } from "../layout/nav";
import { isProfileSlug } from "../profile";

export function NotFound() {
  const { profil } = useParams();
  return (
    <Stack gap="md" align="flex-start">
      <title>Sayfa bulunamadı · finans-takip</title>
      <Title order={1}>Sayfa bulunamadı</Title>
      <Text>Adres yanlış yazılmış ya da sayfa kaldırılmış olabilir.</Text>
      <Anchor component={Link} to={isProfileSlug(profil) ? href(profil, "") : "/"}>
        Özete dön
      </Anchor>
    </Stack>
  );
}
