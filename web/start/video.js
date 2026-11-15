// Recorded demo video. Paste the link between the quotes (YouTube, Vimeo, Google Drive, ...).
// While it is empty, every "Watch the recording" button on the site stays hidden.
const LOWSIGHT_VIDEO_URL = "";

document.querySelectorAll("[data-video]").forEach((a) => {
  if (!LOWSIGHT_VIDEO_URL) return;
  a.href = LOWSIGHT_VIDEO_URL;
  a.target = "_blank";
  a.rel = "noopener";
  a.hidden = false;
});
