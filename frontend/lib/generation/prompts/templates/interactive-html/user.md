Create an interactive learning page for the following concept.

---

## Concept Information

**Concept Name**: {{conceptName}}
**Subject**: {{subject}}
**Concept Overview**: {{conceptOverview}}
**Key Points**: {{keyPoints}}

---

## Scientific Constraints

The following constraints must be strictly obeyed in all JavaScript logic and visualizations:

{{scientificConstraints}}

---

## Interactive Design Idea

{{designIdea}}

---

## Language

**Page language**: {{language}}

(All UI text, labels, instructions, and descriptions must be in this language)

---

## Requirements

1. Complete self-contained HTML5 document
2. Use Tailwind CSS via CDN for styling
3. Pure JavaScript for all interactivity
4. Math formulas in LaTeX format: `\(...\)` for inline, `\[...\]` for display
5. Do NOT include KaTeX - it will be injected automatically
6. All simulations must strictly follow the scientific constraints above
7. Focus on interactive visualization, minimal text
8. Include at least 3 user-operable controls and 1 dynamic feedback area (score/progress/result)
9. Do not output a static title-only or paragraph-only page
10. Ensure interaction content is strongly tied to this lesson's concept/key points (no generic logic drill templates)
11. Prefer card-game interaction form (flip/match/sort/select cards), with every card mapped to lesson knowledge
12. Forbidden: any fallback wording or generic scaffold text unrelated to this lesson

Return the complete HTML document directly.
