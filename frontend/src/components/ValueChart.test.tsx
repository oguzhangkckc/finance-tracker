import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { chart } from "../test/pages";
import { renderPart } from "../test/render";
import { ContributionChart } from "./ContributionChart";
import { ValueChart } from "./ValueChart";

function tableRows() {
  return within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );
}

describe("değerin seyri", () => {
  it("her grafiğin tablo karşılığı vardır; eksik değerler sözcükle yazılır", () => {
    renderPart(<ValueChart chart={chart()} />);

    expect(screen.getByRole("figure", { name: "Değerin seyri" })).toBeInTheDocument();
    expect(tableRows()).toEqual([
      ["11 Kasım", "80.000,00 TL", "79.000,00 TL", "79.500,00 TL"],
      ["18 Kasım", "fiyat eksik", "85.000,00 TL", "85.600,00 TL *"],
      ["25 Kasım", "90.000,00 TL", "85.000,00 TL", "TÜFE yok"],
    ]);
  });

  it("grafik ekran okuyucuya dönemi söyler ve üç çizgiyi açıklar", () => {
    renderPart(<ValueChart chart={chart()} />);

    expect(
      screen.getByRole("img", {
        name: "Haftalık portföy değeri, yatırılan para ve enflasyona göre güncellenmiş yatırım; 11 Kasım ile 25 Kasım arası.",
      }),
    ).toBeInTheDocument();
    const legend = within(screen.getByRole("list", { name: "Çizgiler" }))
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(legend).toEqual([
      "Portföy değeri",
      "Yatırılan para (net katkı)",
      "Enflasyona göre güncellenmiş yatırım",
    ]);
  });

  it.each([
    ["4400", "Değer, enflasyona göre güncellenmiş yatırımın 4.400,00 TL üstünde: reel kazanç."],
    ["-1200.5", "Değer, enflasyona göre güncellenmiş yatırımın 1.200,50 TL altında: reel kayıp."],
    ["0", "Değer, enflasyona göre güncellenmiş yatırıma eşit: reel kazanç ya da kayıp yok."],
  ])("reel fark %s için hüküm yazar", (gap, verdict) => {
    renderPart(<ValueChart chart={chart({ real_gap: gap })} />);

    expect(screen.getByText(verdict)).toBeInTheDocument();
  });

  it("tahmini TÜFE dönemini ay adıyla söyler", () => {
    renderPart(<ValueChart chart={chart()} />);

    expect(
      screen.getByText(
        "TÜFE'si henüz açıklanmamış haftalarda (tabloda *) son açıklanan dönem, Ekim 2026, kullanıldı.",
      ),
    ).toBeInTheDocument();
  });

  it("noktası yoksa hiç çizilmez", () => {
    renderPart(
      <ValueChart chart={chart({ points: [], real_gap: null, estimated_period: null })} />,
    );

    expect(screen.queryByText("Değerin seyri")).not.toBeInTheDocument();
  });
});

describe("katkı geçmişi", () => {
  it("planlanan katkı tanımlı değilse bunu söyler", () => {
    renderPart(
      <ContributionChart
        months={[
          { month: "2026-10", invested: "5000", planned: "5000" },
          { month: "2026-11", invested: "4500.5", planned: null },
        ]}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Son 2 ayın net katkısı ve planlanan aylık katkı; Ekim 2026 ile Kasım 2026 arası.",
      }),
    ).toBeInTheDocument();
    expect(tableRows()).toEqual([
      ["Ekim 2026", "5.000,00 TL", "5.000,00 TL"],
      ["Kasım 2026", "tanımlı değil", "4.500,50 TL"],
    ]);
  });

  it("ay yoksa hiç çizilmez", () => {
    renderPart(<ContributionChart months={[]} />);

    expect(screen.queryByText("Katkı geçmişi")).not.toBeInTheDocument();
  });
});
