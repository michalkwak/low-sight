import { App } from "@wearables-ui-toolkit/mrbd";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Hud } from "./Hud";
// After the toolkit import, so our overrides win at equal specificity (toolkit docs).
import "./hud.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App>
      <Hud />
    </App>
  </StrictMode>,
);
