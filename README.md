# VisPrism

**VisPrism** is an LLM-based multi-agent system for institutional perspective-driven visualization exploration. It enables designers to explore how the same visualization can be designed through different institutional perspectives by representing institutional visualization design knowledge as structured **institutional design personas**.

## Overview

Organizations that repeatedly produce visualizations accumulate distinctive visualization design practices, contextual adaptations, priorities, and values. These forms of knowledge are often documented in visualization style guides and related design resources. We refer to the knowledge encoded in these resources as **institutional visualization design knowledge**.

Different institutions may approach the same visualization problem in substantially different ways. VisPrism makes these institutional perspectives computationally accessible and allows designers to use them as sources of alternative design rationales and design possibilities.

VisPrism supports **Visualization Design Exploration** through three main ideas:

* **Institutional Design Personas.** Each institution is represented as a structured computational representation of its characteristic design perspective.
* **Persona Agents.** Institutional design personas are instantiated as LLM-based agents that apply different institutional perspectives to the same visualization context.
* **Dual-Path Reasoning.** A dual-path reasoning mechanism combines contextual interpretation with knowledge-grounded rule evaluation to determine which institutional knowledge applies to the current visualization.

## Institutional Design Persona

Based on an analysis of **38 institutional style guides** and inspired by McAdams's Three-Tier Model of Personality, VisPrism organizes institutional visualization design knowledge into three dimensions:

* **Design Traits:** stable visualization design practices that characterize an institution across recurring situations.
* **Design Adaptations:** context-dependent rules that apply under particular visualization, data, or communication conditions.
* **Design Identity:** underlying design principles, priorities, and values that guide institutional choices and help resolve ambiguous cases.

Together, these dimensions provide a common structure for representing different institutions while preserving their distinctive design perspectives.

## Visualization Design Exploration

Given a source visualization and a design intent, users can select multiple institutional design personas and explore the **Institution-Specific Design Alternatives** proposed by their Persona Agents.

VisPrism supports designers in:

1. understanding the visualization design perspective of each institution;
2. exploring alternative designs generated from different institutional perspectives;
3. comparing design decisions and rationales across institutions;
4. selectively adopting suggestions from different alternatives; and
5. composing selected decisions into a refined visualization.

Rather than treating an institutional style guide as a fixed set of formatting rules, VisPrism uses institutional visualization design knowledge as a source of context-sensitive design perspectives.

## System Workflow

The VisPrism workflow consists of four major stages:

**1. Persona Construction**

Institutional visualization design resources, primarily institutional style guides, are transformed into structured institutional design personas containing Design Traits, Design Adaptations, and Design Identity.

**2. Institution-Specific Reasoning**

Each Persona Agent independently examines the source visualization and design intent through its institutional perspective. The dual-path reasoning mechanism determines which persona knowledge is applicable to the current visualization context.

**3. Cross-Institutional Exploration**

The resulting Institution-Specific Design Alternatives are presented side by side, allowing users to compare both shared and conflicting design decisions across institutional perspectives.

**4. Selective Composition**

Users can selectively adopt design decisions from different institutional alternatives and compose them into a final visualization.

## Evaluation

We evaluate VisPrism through controlled experiments, a user study, and case studies.

Our evaluation examines:

* whether VisPrism can faithfully apply institutional visualization design knowledge;
* whether institutional knowledge is appropriately adapted to specific visualization contexts;
* whether the resulting visualizations maintain general visualization quality and generation reliability; and
* how designers use institutional perspectives to understand, explore, compare, and synthesize Design Alternatives.

The results demonstrate the potential of VisPrism to support Visualization Design Exploration, generate design inspiration, and refine existing visualization designs.

## Contributions

This work makes three main contributions:

* We introduce **institutional design personas** as a structured representation of institutional visualization design knowledge that preserves distinctive institutional characteristics while supporting cross-institutional comparison.

* We present **VisPrism**, an LLM-based multi-agent system that enables designers to explore visualization designs through different institutional design personas, together with a **dual-path reasoning mechanism** for determining which persona knowledge applies to the current visualization context.

* We evaluate VisPrism through controlled experiments, case studies, and a user study, demonstrating its potential to support exploration of institutional design perspectives, generation of Design Alternatives, and refinement of visualization designs.

## Citation

If you find VisPrism useful in your research, please consider citing our paper:

```bibtex
@article{visprism,
  title   = {VisPrism: ...},
  author  = {...},
  journal = {...},
  year    = {...}
}
```

## License

Please refer to the repository license for details.
