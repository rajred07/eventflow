# Design System Document: The Enterprise Guardian

## 1. Overview & Creative North Star
**Creative North Star: "The Architectural Monolith"**

The design system is built upon the concept of "The Architectural Monolith." In a world of fleeting digital trends, this system stands as a beacon of permanence, security, and structural integrity. It moves beyond the "generic SaaS" look by utilizing heavy typographic weights, intentional negative space, and a sophisticated layering of surfaces that feel like physical architecture rather than pixels.

By rejecting the standard "boxed-in" web grid, we embrace an editorial layout that uses large-scale typography and tonal shifts to guide the eye. We create premium authority not through complexity, but through the extreme precision of alignment and the "breathability" of the canvas.

## 2. Colors: Tonal Authority
We move away from flat hex codes toward a functional hierarchy that mimics light hitting a physical structure.

### Core Palette
- **Primary / Theme Color:** `#000000` (Mapped to `primary`). This represents the "True North" of the brand—unshakeable and absolute.
- **Background:** `#f7f9fb` (Mapped to `background`). A soft, high-end gallery gray that provides a more premium feel than pure white.
- **The Guardian Accent:** `#3980f4` (Mapped to `on_primary_container`). Used sparingly for high-impact actions and progress indicators.

### The "No-Line" Rule
To achieve a high-end editorial feel, **1px solid borders are strictly prohibited for sectioning.** 
*   **The Transition:** Boundaries must be defined solely through background color shifts. For example, a `surface_container_low` section should sit directly against a `background` section to define a new content area.
*   **The Signature Gradient:** For Hero Banners and primary CTAs, use a subtle radial gradient from `primary` to `primary_container`. This adds a "soul" to the navy depth, preventing it from feeling flat or "dead."

### Surface Hierarchy & Nesting
Treat the UI as a series of nested, high-quality materials:
1.  **Base Layer:** `background` (#f7f9fb)
2.  **Section Layer:** `surface_container_low` (#f2f4f6)
3.  **Component Layer (Cards/Modals):** `surface_container_lowest` (#ffffff)
4.  **Interaction Layer:** `surface_bright` (#f7f9fb)

## 3. Typography: Editorial Precision
The system uses a dual-font strategy to balance corporate authority with modern accessibility.

*   **Display & Headlines (Manrope):** Chosen for its geometric stability. At `display-lg` (3.5rem) and `headline-lg` (2.0rem), the tight kerning and heavy weights should feel like an annual report from a Fortune 500 firm. Use `on_surface` (#191c1e) for maximum contrast.
*   **Body & UI (Inter):** The industry standard for legibility. At `body-md` (0.875rem), it ensures that complex event data—like room inventory and budget receipts—remains crystal clear.
*   **The "Guardian" Lead:** Use `title-lg` for introductory paragraphs to establish a "Director’s Voice" before moving into standard body copy.

## 4. Elevation & Depth: Tonal Layering
We eschew "material" shadows in favor of ambient environmental light.

*   **The Layering Principle:** Depth is achieved by "stacking" surface tiers. A `surface_container_lowest` card placed on a `surface_container_low` background creates a natural lift.
*   **Ambient Shadows:** For "floating" elements like budget modals or room cards, use a shadow with a 24px-32px blur and 4% opacity. The color should be tinted with `on_surface_variant` (#45464d) to feel like a natural shadow rather than a gray smudge.
*   **Glassmorphism & Depth:** For Hero navigation and floating overlays, use a background of `surface_container_lowest` at 80% opacity with a `20px backdrop-blur`. This ensures the content "belongs" to the background while maintaining legibility.
*   **The Ghost Border Fallback:** If a boundary is required for accessibility, use `outline_variant` (#c6c6cd) at **15% opacity**. It should be felt, not seen.

## 5. Components

### Hero Banners
*   **Visual:** Deep Navy (`primary_container`) backgrounds with a dark linear gradient overlay (45 degrees) to ensure text legibility.
*   **Alignment:** Use intentional asymmetry. Left-aligned typography with 60% width, leaving the right 40% for high-end photography or "Glass" UI elements.

### Floating Cards (Room Inventory)
*   **Structure:** White (`surface_container_lowest`) with `xl` (0.75rem) rounded corners.
*   **Status Badges:** Use `on_error_container` (#93000a) for urgent status (e.g., "2 rooms left") but set it on `error_container` (#ffdad6) to keep it professional, not alarming.
*   **Spacing:** No dividers. Use `1.5rem` of internal padding to separate image, title, and price.

### Budget Visualization (Receipts/Progress)
*   **Progress Bars:** Use a `secondary_container` (#dae2fd) track with an `on_primary_container` (#3980f4) fill.
*   **The Receipt UI:** Use a `surface_container_low` background. Typography should be `label-md` for line items, creating a "monospaced" clean tabular look.

### Buttons & Inputs
*   **Primary Button:** `on_primary_container` background with `on_primary` text. No border. `md` (0.375rem) corner radius for a sharp, corporate feel.
*   **Input Fields:** Ghost-style. Background of `surface_container_low` with a `1px` ghost border (15% opacity `outline_variant`). On focus, transition to a `2px` `on_primary_container` bottom-only border.

## 6. Do’s and Don’ts

### Do:
*   **Use White Space as a Tool:** If a layout feels cluttered, increase the margin—do not add a line.
*   **Lead with Type:** Use the `display-md` scale to make bold statements.
*   **Nesting Surfaces:** Use the "Lowest-to-Highest" surface rule to create hierarchy.

### Don’t:
*   **Never use pure black text:** Always use `on_surface` (#191c1e) to maintain a premium "ink" look rather than a "system" look.
*   **Avoid 100% Opacity Borders:** They break the architectural flow and feel "templated."
*   **No Standard Drop Shadows:** Avoid the default "Figma" shadow. Always blur more and reduce opacity more than you think is necessary.