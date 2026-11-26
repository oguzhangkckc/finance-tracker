import { Icon } from "../layout/icons";
import type { ProfileSlug } from "../profile";

// K-125: her önizleme ve onay ekranında hangi portföye yazılacağı kalın bir kutuda.
export function TargetProfile({ profile }: { profile: ProfileSlug }) {
  return (
    <p className="ft-target">
      <Icon name="hedef" size={22} />
      {profile === "sanal" ? (
        <span>
          <strong>SANAL</strong> portföye kaydedilecek. Gerçek alım değil.
        </span>
      ) : (
        <span>
          <strong>GERÇEK</strong> portföye kaydedilecek.
        </span>
      )}
    </p>
  );
}
