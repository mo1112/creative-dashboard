// Shared Meta link helpers (ad list modal + Attribution tab).

// Opens Meta links in a new tab ourselves: a plain target="_blank" click was being
// swallowed in some browsers (nothing happened). If the new tab is blocked, open here.
export function openExternal(e, url) {
  if (!url || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  const w = window.open(url, "_blank");
  if (w) { try { w.opener = null; } catch {} } else window.location.assign(url);
}

// Ads Manager links open inside the ad's own account, and its business when known,
// so viewers with several businesses don't land in their personal one.
let BUSINESS_IDS = {};
let DEFAULT_ACCOUNT = "";
export function setBrand(brand, accounts) {
  BUSINESS_IDS = brand?.business_ids || {};
  DEFAULT_ACCOUNT = (accounts || [])[0] || "";
}
function accountParams(account) {
  const act = String(account || DEFAULT_ACCOUNT).replace(/^act_/, "");
  const biz = BUSINESS_IDS[act];
  return `act=${act}` + (biz ? `&business_id=${biz}&global_scope_id=${biz}` : "");
}
export function adsManagerUrl(account, adIds) {
  const ids = (adIds || []).filter(Boolean);
  if (!ids.length) return null;
  // The ad's edit view shows its preview and also opens archived/deleted ads.
  return `https://adsmanager.facebook.com/adsmanager/manage/ads/edit/standalone?${accountParams(account)}&selected_ad_ids=${ids[0]}`;
}

// Campaign / ad set in Ads Manager (edit view: opens archived ones too).
function levelUrl(level, account, id) {
  if (!id) return null;
  return `https://adsmanager.facebook.com/adsmanager/manage/${level}s/edit/standalone?${accountParams(account)}&selected_${level}_ids=${id}`;
}
export const campaignUrl = (account, id) => levelUrl("campaign", account, id);
export const adsetUrl = (account, id) => levelUrl("adset", account, id);
