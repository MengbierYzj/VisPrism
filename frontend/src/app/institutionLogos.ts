import type { PersonaMeta } from "./api";

const LOGO_DIRECTORY = "/institution-logos";

export type InstitutionLogoShape = "rounded" | "circle";

export interface InstitutionLogoPresentation {
  path: string;
  shape: InstitutionLogoShape;
  paddingRatio: number;
}

const LOGO_ALIASES: Record<string, string> = {
  amazon: "amazon.png",
  apple: "apple.png",
  aviva: "aviva.png",
  "baltimore-city-data-fellows-project": "baltimore-city-data-fellows-project.png",
  bbc: "bbc.png",
  "bbc-visual-journalism": "bbc.png",
  "carnegie-mellon-univeristy": "carnegie-mellon-university.png",
  "carnegie-mellon-university": "carnegie-mellon-university.png",
  "cato-institute": "cato-institute.png",
  clarity: "clarity.png",
  "clarity-design-system": "clarity.png",
  "consumer-financial-protection-bureau": "consumer-financial-protection-bureau.png",
  cfpb: "consumer-financial-protection-bureau.png",
  "dallas-morning-news": "dallas-morning-news.png",
  dell: "dell.png",
  ebay: "ebay.png",
  economist: "economist.png",
  "the-economist": "economist.png",
  gitlab: "gitlab.png",
  google: "google.png",
  "government-of-canada": "government-of-canada.png",
  ibm: "ibm.png",
  "justice-innovation-lab": "justice-innovation-lab.png",
  "kraft-heinz": "kraft-heinz.png",
  "kraft-heinz-delish-design-system": "kraft-heinz.png",
  "london-city-intelligence": "london-city-intelligence.png",
  metlife: "metlife.png",
  "met-life": "metlife.png",
  michelin: "michelin.png",
  microsoft: "microsoft.png",
  "monash-climate-change-communication-research-hub-mcccrh": "mcccrh.png",
  mcccrh: "mcccrh.png",
  nzz: "nzz.png",
  "nzz-visuals": "nzz.png",
  "office-for-national-statistics": "office-for-national-statistics.png",
  ons: "office-for-national-statistics.png",
  "red-hat": "red-hat.png",
  redhat: "red-hat.png",
  salesforce: "salesforce.png",
  shopify: "shopify.png",
  "sprout-social": "sprout-social.png",
  "sunlight-foundation": "sunlight-foundation.png",
  taso: "taso.png",
  "the-urban-institute": "the-urban-institute.png",
  "urban-institute": "the-urban-institute.png",
  tractie: "tractie.png",
  "tractie-ns-dutch-railways": "tractie.png",
  twilio: "twilio.png",
  "u-s-design-system": "us-design-system.png",
  "us-design-system": "us-design-system.png",
  uswds: "us-design-system.png",
  visma: "visma.png",
  "visma-s-unified": "visma.png",
  "world-health-organization": "world-health-organization.png",
  who: "world-health-organization.png",
};

const CIRCULAR_LOGOS = new Set([
  "apple.png",
  "baltimore-city-data-fellows-project.png",
  "google.png",
]);

function normalizeInstitutionName(value: string) {
  return value
    .replace(/\.(?:md|markdown|ya?ml)$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function institutionLogoFilename(persona: PersonaMeta) {
  const identities = [persona.id, persona.name, persona.full_name, persona.source];
  for (const identity of identities) {
    const filename = LOGO_ALIASES[normalizeInstitutionName(identity || "")];
    if (filename) return filename;
  }
  return null;
}

export function institutionLogoPresentation(persona: PersonaMeta): InstitutionLogoPresentation | null {
  const filename = institutionLogoFilename(persona);
  if (!filename) return null;

  const shape: InstitutionLogoShape = CIRCULAR_LOGOS.has(filename) ? "circle" : "rounded";
  return {
    path: `${LOGO_DIRECTORY}/${filename}`,
    shape,
    paddingRatio: shape === "circle" ? 0 : 0.08,
  };
}
