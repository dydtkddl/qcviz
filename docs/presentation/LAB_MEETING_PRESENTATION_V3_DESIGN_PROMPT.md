# Lab Meeting Presentation V3 Visual Design Prompt

## Goal

Upgrade the existing lab meeting presentation into a conference-style and government-briefing-style deck that feels more deliberate, credible, and visually substantial without becoming decorative noise. The deck must still read as a scientific presentation, but section divider slides and high-level slides should now feel closer to a formal research briefing, a national R&D planning deck, or a polished proposal presentation.

The V3 deck should solve two concrete weaknesses identified in V2:

1. Section divider slides feel too plain and generic.
2. Standard content slides feel structurally clean but somewhat flat.

The upgraded deck must therefore add stronger slide architecture, richer visual hierarchy, and more "briefing document" texture while preserving readability and avoiding any overlap, clipping, or fragile layout behavior.

## Audience

The primary audience is a mixed chemistry lab group:

- experimental chemists
- computational/theoretical chemists
- research supervisors evaluating project direction

They do not need code-level detail. They need confidence, clarity, scientific relevance, and a sense that the project is mature enough to discuss as a research tool and planning asset.

## Research-Informed Style Direction

Synthesize the following visual cues from academic conference decks and government / proposal style slides:

- Academic decks favor strong hierarchy, readable typography, clear summaries, and visually obvious section transitions.
- Government and public-sector proposal decks often use structured header bands, briefing labels, metadata strips, chapter numbers, and clean but assertive geometry.
- Strong section divider slides often include large section numerals, layered blocks, diagonal structural accents, and a subtitle or keyword strip that signals what the section will cover.
- Professional proposal decks often use restrained but visible framing devices: top-right metadata blocks, section labels, timeline or chapter cues, and informative chrome that makes the slides feel designed rather than plain.

## Design Intent

The deck should feel like:

- a scientific platform presentation prepared for a conference or internal review
- a credible project-planning deck for a funded research proposal
- a modern briefing package rather than a student class presentation

It should not feel like:

- a consumer startup pitch deck
- a playful marketing deck
- a minimal template with only text on white slides

## Global Visual Language

Keep the existing white background and strong conference palette, but add more structure:

- use a light architectural header zone on standard slides
- add a top-right briefing block or metadata strip on most slides
- introduce subtle geometric framing that suggests planning, systems thinking, and institutional polish
- keep all geometry angular and rectilinear
- use no rounded corners, no drop shadows, and no gradients

The slide should look intentionally engineered.

## Section Divider Slide Rules

Completely redesign the divider slides so they no longer look like plain blue pages with centered text.

Each divider slide should include:

- a full-bleed primary blue base
- one or more darker or lighter angular structural overlays
- a very large section number or chapter code
- a prominent section title
- a short subtitle describing the section's purpose
- a bottom metadata band or keyword strip
- optional thin grid or briefing-line accents that imply planning / systems structure

The visual mood should resemble:

- conference plenary chapter covers
- government project briefing covers
- national R&D proposal section openers

These slides should feel richer, denser, and more cinematic than normal content slides, while still remaining clean and formal.

## Standard Content Slide Rules

Standard slides should also be upgraded so they are less flat:

- retain the white body for readability
- add a structured header system with a stronger title area
- reserve space for a right-side or upper-right briefing block
- use a thin metadata strip, section tag, or mini progress cue when possible
- introduce one subtle supporting geometry element per slide category where it helps framing

This added structure must not compete with the content. It exists to make the deck feel designed, not crowded.

## Layout Safety Rules

No slide may contain overlapping or clipped text.

Apply the following safeguards:

- preserve at least 0.45-0.50 inch outer padding
- keep title and header ornaments inside a dedicated top band
- ensure content zones begin below the header system
- if a title becomes long, allow safe wrapping or slightly reduce font size automatically rather than colliding with header elements
- keep footer, bottom bar, and slide number clear of all content
- image placeholders and diagrams must remain inside the canvas with safe breathing room

Do not create any layout that depends on pixel-perfect luck.

## Typography Intent

Slightly increase readable text size from V2, but do so selectively:

- title text should remain strong and formal
- subtitles should be more legible at distance
- small labels should stay compact but crisp
- dense slides should still be readable when projected

Avoid making slides feel bloated. The goal is controlled presence, not oversized text.

## Image and Diagram Strategy

Feature slides and demo slides should continue using explicit placeholders, but the framing around those placeholders should feel more intentional:

- placeholders should sit inside stronger panels where useful
- comparison slides should use more deliberate grouping
- architecture and pipeline slides should feel like briefing diagrams, not simple classroom boxes

If a slide is primarily text-heavy, use structural framing so it still looks visually anchored.

## Content Additions Worth Including

If the current deck lacks them, a conference-style or proposal-style version benefits from:

- clearer "why now" framing
- more explicit evidence / validation status framing
- one slide that distinguishes current implementation from future validation
- one slide that frames the platform as a research-enablement system, not only a software demo

Add only items supported by the project scan and existing lab meeting materials.

## Implementation Brief For The Generator

Use the V2 presentation as the functional baseline, but apply the following upgrades for V3:

1. Replace the current plain divider slide with a layered chapter-cover layout.
2. Strengthen the title / subtitle header zone on standard slides.
3. Add a reusable briefing-style chrome element on most non-divider slides.
4. Keep the overall deck academically professional, not flashy.
5. Maintain speaker notes and all current narrative content unless a change improves presentation logic.
6. Validate output so no rendering-error slides appear and the file reopens successfully.

## Reference Inspiration

These references informed the visual direction and presentation-structure ideas:

- George Washington University School of Medicine session slide best practices: https://cfe.smhs.gwu.edu/sites/g/files/zaskib506/files/2025-02/best_practices_on_session_slide_development.pdf
- POMA slide design guidelines: https://poma.memberclicks.net/assets/committee/Curriculum/POMA%20Slide%20Design%20Guidelines.pdf
- Slidesgo government agency template gallery: https://slidesgo.com/theme/government-agency
- SlidesCarnival government and public services template gallery: https://www.slidescarnival.com/template/government-and-public-services
- GoodPello graphical slide section design examples: https://www.goodpello.com/en/products/17133
- City and County of San Francisco grant application pitch deck guidance: https://www.sf.gov/information--our-grant-application-pitch-deck

## Final Output Expectation

Produce a separate V3 PowerPoint file that feels visibly more mature than V2, especially on section-divider slides and other high-level slides, while staying clean, academic, and layout-safe.
