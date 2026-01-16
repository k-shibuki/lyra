---
title: "Phase Diagrams for Human–AI Development: An Observational Theory of Finalization and Responsibility"
tags:
  - design theory
  - human–AI collaboration
  - phase diagram
  - finalization
  - responsibility
  - correctness reference system
authors:
  - name: Katsuya Shibuki
    orcid: 0000-0003-3570-5038
    affiliation: 1
affiliations:
  - name: Independent Researcher
    index: 1
date: 16 January 2026
bibliography: paper.bib
---

# Abstract

In human–AI collaborative development, the generation of change units (e.g., PRs, diffs, change requests) accelerates and the number of concurrent change processes increases. Meanwhile, exposure to irreversible loss (safety, legal, economic, reputational, etc.) and accountability ultimately collapse at a responsibility-fold point (RP) coupled to observable finalization events. As generation pressure (arrival rate × concurrency) grows, the RP fold point’s effective service rates for finalization and for maintaining the correctness reference system (CRS) and verification recipes (VR) can become bottlenecks. The operational regime may then exhibit phase transitions—sudden shifts from stable to failure modes—regarding (a) controllability (whether unfinalized WIP remains bounded), (b) CP health (whether CRS/VR remain coherent rather than stale), and (c) reproducibility (whether the same verification recipe yields a unique finalized state).

This paper separates the development system into a Data Plane (DP; object layer) and a Control Plane (CP; meta layer), and proposes an observational language that describes phase transitions using variables estimable from logs. Core variables include the finalization load ratio $\rho$, CRS staleness pressure $\Pi$, verification-recipe (VR) staleness pressure $\Psi$, a non-commutativity proxy $1-\hat p_\Delta$, a reproducibility-loss proxy $\hat\varepsilon$, proxies for verification-gate detector performance, exploration share $\hat s$, CRS resolution $\hat R$, and phase-diagram coordinates such as concurrency pressure $\kappa$ and the “non-commutativity × strictness” summary $\chi$. Phase transitions are defined observationally as structural changes in distributional shape, with heavy-tailed cycle-time distributions as a canonical example. This paper makes projection relations among phase diagrams explicit, provides two example class propositions (non-monotone boundaries; possible reproducibility loss under concurrent finalization with non-commutative updates), and enumerates falsifiability conditions.

The goal is to avoid premature heuristic short-circuits from experience and instead describe diverse futures (centralized review, formalization and automated verification, exploration-heavy regimes, relaxed reproducibility requirements, institutional shifts in responsibility) as movements of phase boundaries.

---

# 0. Positioning (Theoretical Stance)
## 0.1 Objective

To avoid prematurely collapsing experience into a single success narrative, this paper delivers:

1. **Variable definitions**: quantities estimable (or approximable via proxies) from operational logs
2. **Phase diagrams**: visualization of failure/stability modes and branching conditions
3. **Falsifiability conditions**: quantitative criteria under which the framework is refuted or requires revision

This paper's observational language was motivated by experience in a project building operational software with AI coding agents without code inspection [@shibukiZeroHumanCode2026]. That project succeeded under specific conditions, but this paper does not claim those conditions generalize; the goal is to provide a language describing diverse futures as movements of phase boundaries.

## 0.2 Stance (semi-formal / falsifiability-oriented)

This paper uses formal notation but does **not** aim for closed-form solutions or global optimization. Following Box's perspective on models as approximations [@boxScienceStatistics1976], the question here is usefulness rather than optimality. The goal is a transferable language for design and operation of human–AI collaboration under potential phase transitions, connected to observables.

## 0.3 Example class propositions

The propositions here are not universal theorems; they illustrate sufficient conditions within a class of assumptions. Even if a proposition fails empirically, the observational language (variables, phase diagrams, falsifiability) remains useful.

---

# 1. Responsible Principal (RP)

In this paper, **RP (Responsible Principal)** is not an “actor” per se. RP is a **responsibility-fold point**: the locus at which exposure to irreversible loss (safety, legal, economic, reputational, etc.) and accountability ultimately **collapse** at **finalization events**, consistent with safety-engineering perspectives on control and accident risk [@levesonEngineeringSaferWorld2012; @perrowNormalAccidentsLiving1984]. Work can be distributed up to this fold point (across humans, AI agents, teams, tools, and institutions), but beyond finalization events responsibility becomes consolidated by design or by institution.

Operationally, the RP fold point is the place where the system must (i) execute/approve **finalization events** and (ii) maintain/update the **correctness reference system (CRS)** that defines correctness. In current institutions, implementations of RP are typically human individuals or organizations; however, the framework does not assume a particular implementation (human vs non-human, single vs multi-party, centralized vs distributed), only that the fold point exists.

The RP fold point has at least three finite effective “bandwidth” resources (notation fixed throughout):

* **finalization bandwidth** $C_{\mathrm{RP,fin}}(t)$: capacity (service rate) to process finalization events (judgment, audit, approval)
* **CRS maintenance bandwidth** $C_{\mathrm{RP,CRS}}(t)$: capacity to maintain/update the normative/semantic reference system
* **VR maintenance bandwidth** $C_{\mathrm{RP,VR}}(t)$: capacity to maintain/update verification recipes (operational gates)

---

# 2. Two-Plane Model: Data Plane and Control Plane (object/meta)

## 2.1 Definitions and mapping

* **Data Plane (DP)**: the object layer (artifacts, states, implementations) updated by change units
* **Control Plane (CP)**: the meta layer (norms, criteria, recovery standards)

The CP/DP terminology is borrowed from network engineering [@kuroseCOMPUTERNETWORKINGTOPDOWN2025], but its meaning matches the meta/object decomposition (normative criteria vs artifacts/states). This paper treats **CP $\equiv$ meta layer** and **DP $\equiv$ object layer**. This separation aligns with the end-to-end argument in system design [@saltzerEndtoendArgumentsSystem1984].

This paper decomposes CP into functional components:

* **CRS (correctness reference system)**: the normative/semantic reference defining correctness
* **VR (verification recipes)**: operational procedures mapping CRS into practical judgments; detectors approximating correctness (operationalization of correctness)
* **RC (rules/commands)**: constraints (rules) and recovery standards (commands); not verification procedures

CRS and VR are distinct: **CRS defines correctness** as a normative reference [@dijkstraHumbleProgrammer1972]; **VR operationalizes it as detectors** whose performance is subject to misclassification and measurement error [@greenlandVarianceEstimationEpidemiologic1988; @carrollMeasurementErrorNonlinear2006]. This is a functional decomposition and does not require physical or organizational separation.[^impl]

[^impl]: Minimal implementation listing: CP (meta layer) = CRS + VR (verification gates/recipes) + rules + commands; DP (object layer) = change units (diff/PR/ticket, etc.) + verification artifacts (tests/analyses/audit scripts) + artifacts/states.

## 2.2 Conceptual diagram

![Control Plane / Data Plane conceptual diagram. CP contains CRS, VR, rules, and commands. DP contains change units, verification artifacts, and states.](figures/figure1-cp-dp.pdf)

---

# 3. Logging Schema (observability)

## 3.1 Change unit

A “change unit” is any unit (PR, diff, change request, bundled commits, etc.) for which one can define:

* an arrival time
* linkage to verification-recipe (gate) attempts
* linkage to a finalization event (merge/release/regulatory enactment/audit approval, etc.)
* traceable rework (review rounds, retries, revert/hotfix)

## 3.2 Finalization event (observational definition of irreversibility)

Finalization is a concept; **finalization events** are observable. A finalization event is defined as a boundary after which rollback is materially constrained (costly, delayed, or institutionally prohibited), thereby coupling the system state to irreversible loss exposure [@grayNotesDataBase1978; @bernsteinConcurrencyControlRecovery1987] and anchoring the RP definition to observable events.

(Example proxies: rollback cost, recovery lead time, incident severity, audit/regulatory impact.)

## 3.3 “No backlog” environments

Even without an explicit backlog list, WIP exists and can be observed via delay proxies (cycle time, waiting time, retry density). Hence the model remains applicable.

---

# 4. Core Metrics: $\rho$ (finalization), $\Pi$ (CRS), $\Psi$ (VR)

## 4.1 Finalization load ratio $\rho$ (controllability)

### 4.1.1 Total inflow (closed-loop included)

$$
A_{\text{tot}}(t)=A_{\text{new}}(t)+A_{\text{rw}}(t)
$$

* $A_{\text{new}}(t)$: newly arriving change units
* $A_{\text{rw}}(t)$: re-arrivals due to rework

Rework rate (proxy):
$$
r(t)=\mathbb{E}\big[\#(\text{review rounds}+\text{gate retries}+\text{revert/hotfix})\mid t\big]
$$

Approximation:
$$
A_{\text{tot}}(t)\approx A_{\text{new}}(t)\cdot (1+\beta r(t))
$$

### 4.1.2 Per-unit finalization cost $w_{\text{fin}}$

$$
w_{\text{fin}}(t)=
c_{\text{rev}}\cdot \#\text{review rounds}
+
c_{\text{gate}}\cdot \#\text{gate retries}
+
c_{\text{conf}}\cdot \#\text{conflicts}
+
c_{\text{rb}}\cdot \#\text{rollback}
$$

### 4.1.3 Load ratio

$$
\rho(t)=\frac{A_{\text{tot}}(t)\cdot w_{\text{fin}}(t)}{C_{\mathrm{RP,fin}}(t)}
$$
Sustained $\rho>1$ indicates a regime where unfinalized WIP tends to diverge [@littleProofQueuingFormula1961; @harchol-balterPerformanceModelingDesign2013].

## 4.2 CRS staleness pressure $\Pi$

DP updates induce demand for CRS updates. Let $\lambda_{\mathrm{CRS}}(t)$ be the arrival rate of CRS update demands and $w_{\mathrm{CRS}}(t)$ their expected cost:

$$
\Pi(t)=\frac{\lambda_{\mathrm{CRS}}(t)\cdot w_{\mathrm{CRS}}(t)}{C_{\mathrm{RP,CRS}}(t)}
$$

Induced-demand mechanism (one-line summary for separability from VR):
$$
\lambda_{\mathrm{CRS}}(t)=g_{\mathrm{CRS}}\Big(\lambda_{\text{new}}(t),\ 1-\hat p_\Delta(t),\ \text{domain shift proxies}(t),\ \hat R(t),\ \dots\Big)
$$

## 4.3 VR staleness pressure $\Psi$

DP updates also induce demand for VR (verification recipe) updates. Let $\lambda_{\mathrm{VR}}(t)$ be the arrival rate of VR update demands and $w_{\mathrm{VR}}(t)$ their expected cost:

$$
\Psi(t)=\frac{\lambda_{\mathrm{VR}}(t)\cdot w_{\mathrm{VR}}(t)}{C_{\mathrm{RP,VR}}(t)}
$$

Induced-demand mechanism:
$$
\lambda_{\mathrm{VR}}(t)=g_{\mathrm{VR}}\Big(\lambda_{\text{new}}(t),\ \text{detector proxies}(t),\ \text{flake rate}(t),\ \text{artifact drift proxies}(t),\ \dots\Big)
$$

Example proxies for VR staleness: recipe-revision event density; variance spikes in gate-failure rates; repeated retries due to the same root cause.

---

# 5. Non-commutativity, reproducibility, and verification-gate detectors

## 5.1 Non-commutativity proxy $\hat p_\Delta$

$$
\hat p_\Delta(t)=1-\Pr(\text{conflict}=1\mid \text{concurrent within window }\Delta\text{ at }t)
$$
Window $\Delta$ is fixed for comparability; commutativity and serializability are central concerns in concurrent systems [@bernsteinConcurrencyControlRecovery1987].

## 5.2 Reproducibility loss proxy and requirement

$$
\hat\varepsilon(t)=\Pr(\text{non-identical outcome}=1\mid \text{same verification recipe at }t)
$$
$\varepsilon_{\max}$ is an operational SLO; sustained $\hat\varepsilon>\varepsilon_{\max}$ indicates violation. Conflict-free replicated data types (CRDTs) provide one approach to commutativization by design [@shapiroConflictFreeReplicatedData2011].

## 5.3 Detector performance (proxies)

Verification gates are treated as detectors. When $(\mathrm{TPR},\mathrm{FPR})$ is not identifiable, approximate detector performance via proxies such as post-finalization incident rates, audit findings, or recurrence rates after rework [@greenlandVarianceEstimationEpidemiologic1988; @carrollMeasurementErrorNonlinear2006]. Increased false-positive proxies can increase retries and push $\rho\uparrow$ through the rework loop.

---

# 6. Exploration/Execution two-phase view and CRS resolution

## 6.1 Two phases

* **Exploration**: updates that increase CP resolution (CRS/VR) and decision-ability
* **Execution**: DP updates (implementation, modification, repair) to satisfy CP constraints
  Debugging is treated as a subtype of execution, not a separate phase. This two-phase view aligns with the exploration–exploitation framework in organizational learning [@marchExplorationExploitationOrganizational1991].

## 6.2 Exploration share $\hat s$

$$
\hat s(t)=\frac{\#\text{exploration updates (pre-finalization)}}{\#\text{all updates (exploration+execution)}}
$$

## 6.3 CRS resolution $\hat R$

$$
\hat R(t)=
w_1\cdot \#\text{contract clauses}
+
w_2\cdot \#\text{CRS-aligned invariants}
+
w_3\cdot \#\text{explicit boundary definitions}
$$
$\hat R$ measures resolution as operationalizable decision criteria, not prose volume.

**Directional implication**: generally $\hat s\uparrow$ is expected to be accompanied by $\hat R\uparrow$ (unless exploration degenerates into non-operational prose). Typically:

* $\hat R\uparrow \Rightarrow r\downarrow,\ 1-\hat p_\Delta\downarrow,\ \hat\varepsilon\downarrow$.
* Exploration that does not increase $\hat R$ can increase $w_{\mathrm{CRS}}$ and push $\Pi\uparrow$.

---

# 7. Concurrency pressure $\kappa$: observable “arrival rate × concurrency”

Let $\lambda_{\text{new}}(t)$ be the new arrival rate and $L(t)$ a concurrency-window proxy (parallel WIP). Define:
$$
I(t):=\lambda_{\text{new}}(t)\cdot L(t)
$$
and nondimensionalize by RP finalization bandwidth:
$$
\kappa(t)=\frac{\lambda_{\text{new}}(t)\cdot L(t)}{C_{\mathrm{RP,fin}}(t)}.
$$

---

# 8. Projection relations and $\chi$

$$
\rho=\rho(\kappa,\hat p_\Delta,\hat\varepsilon,\text{detector proxy},\hat s,\hat R,\dots)
$$
$$
\Pi=\Pi(\kappa,g_{\mathrm{CRS}},\hat R,\dots),\quad
\Psi=\Psi(\kappa,g_{\mathrm{VR}},\text{detector proxy},\dots)
$$

Define a dimensionless “non-commutativity × strictness” summary:
$$
\chi := f!\left(1-\hat p_\Delta,\ \varepsilon_{\max};\ \Delta\right),
\quad
\text{and in this paper I use the simple instantiation }f=\frac{1-\hat p_\Delta}{\varepsilon_{\max}}.
$$

![Projection relations among variables. κ drives ρ, Π, Ψ. Exploration share ŝ influences resolution R̂, which affects commutativity and reproducibility proxies.](figures/figure2-projection.pdf)

---

# 9. Observational definition of phase transitions and phase diagrams

## 9.1 Observational definition (distribution-shape change)

A phase transition here means a structural change in distributional shape (not merely a smooth mean shift). A canonical example is heavy-tailed cycle-time distributions [@clausetPowerLawDistributionsEmpirical2009] (rapid growth of upper quantiles, tail-index change) for time-to-finalization. Regions where such structural changes persist are treated as transitions from stable to failure regimes. Self-exciting point processes can model event clustering in failure cascades [@hawkesSpectraSelfexcitingMutually1971].

## 9.2 Phase A-CRS: $(\rho\times\Pi)$

![Phase A-CRS diagram: ρ (finalization load) × Π (CRS staleness). Quadrants show stable, CRS failure, throughput failure, and joint failure regions.](figures/figure3-phase-a-crs.pdf)

## 9.3 Phase A-VR: $(\rho\times\Psi)$

![Phase A-VR diagram: ρ (finalization load) × Ψ (VR staleness). Quadrants show stable, VR failure, throughput failure, and joint failure regions.](figures/figure4-phase-a-vr.pdf)

**Joint-failure region (illustrative sufficient condition)**:
$$
(\rho\ \text{high})\ \wedge\ \big((\Pi\ \text{high})\ \vee\ (\Psi\ \text{high})\big).
$$

Which component tends to lead (CRS-driven vs VR-driven) is domain-dependent: high regulation/audit/safety constraints often yield CRS-driven failure, while high implementation drift and verification-artifact drift often yield VR-driven failure.

## 9.4 Phase B: finalization constraint phase (non-commutativity × strictness)

![Phase B diagram: non-commutativity ($1-\hat p_\Delta$) × strictness ($\varepsilon_{\max}$). Quadrants show low friction, formalization OK, speed-first, and high serialization pressure.](figures/figure5-phase-b.pdf)

## 9.5 Phase C: configuration phase $(\kappa\times\chi)$

![Phase C diagram: κ (concurrency pressure) × χ (non-commutativity × strictness). Quadrants show stable, decentralize OK, failure likely, and centralized finalization valuable.](figures/figure6-phase-c.pdf)

---

# 10. Flat enumeration of futures (branching regimes)

* **Fut-1: Centralized finalization dominates**
  $\kappa\uparrow$ and $\chi\uparrow$. Finalization becomes a structural bottleneck.
* **Fut-2: Formalization and automated verification dominate**
  $1-\hat p_\Delta\downarrow$ and improved detector proxies reduce the need for centralized review.
* **Fut-3: Exploration and resolution dominate**
  $\hat s\uparrow,\hat R\uparrow$ reduce $r$ and suppress $\rho$, absorbing increases in $\kappa$.
* **Fut-4: Speed-first via relaxed reproducibility requirements**
  $\varepsilon_{\max}\uparrow$ implies $\chi\downarrow$, shifting Phase B toward the lenient region.
* **Fut-5: VR fails first**
  $\Psi\uparrow$ precedes $\Pi\uparrow$, increasing gate-induced rework and pushing $\rho\uparrow$.
* **Fut-6: Reference maintenance ceases to dominate**
  $\max{\Pi,\Psi}$ remains low (localization/automation), shifting focus to audit/recovery/incident control.

---

# 11. Example class propositions

## Proposition 1 (existence of non-monotone boundary): conditions under which $\rho(a)$ can have a minimum

For an intervention level $a\in[0,1]$ (encompassing automation, AI assistance, and parallelization), consider:
$$
\rho(a)=\frac{A(a),G(a),w_{\text{fin}}(a)}{C_{\mathrm{RP,fin}}(a)},\quad
G(a)=1+\beta r(a)
$$
Taking a log-derivative:
$$
\frac{\rho'(a)}{\rho(a)}=
\frac{A'}{A}+\frac{G'}{G}+\frac{w_{\text{fin}}'}{w_{\text{fin}}}-\frac{C_{\mathrm{RP,fin}}'}{C_{\mathrm{RP,fin}}}
\tag{LD}
$$
If there exists $a^*\in(0,1)$ such that
$$
\frac{A'}{A}+\frac{G'}{G}+\frac{w_{\text{fin}}'}{w_{\text{fin}}}-\frac{C_{\mathrm{RP,fin}}'}{C_{\mathrm{RP,fin}}}=0
\tag{C1}
$$
and
$$
\left(\frac{A'}{A}+\frac{G'}{G}+\frac{w_{\text{fin}}'}{w_{\text{fin}}}-\frac{C_{\mathrm{RP,fin}}'}{C_{\mathrm{RP,fin}}}\right)'\Big|_{a=a^*}>0,
\tag{C2}
$$
then $\rho(a)$ can have a local minimum at $a^*$ (a U-shape is possible). Since $A(a)$ is exogenous, convexity of $r(a)$ alone does not imply a U-shape; the boundary is determined by the balance of relative change rates among $A,w_{\text{fin}},C_{\mathrm{RP,fin}},r$ [@stermanBusinessDynamicsSystems2000].

## Proposition 2 (existence claim): non-commutativity with concurrent finalization can produce reproducibility loss

Define “concurrent finalization” as a finalization window $[t,t+\Delta]$ in which the multiset of updates is not totally ordered and application order can depend on scheduling. If non-commutative update pairs occur with positive probability within the window [@bernsteinConcurrencyControlRecovery1987; @shapiroConflictFreeReplicatedData2011], the same verification recipe can yield divergent outcomes, implying $\hat\varepsilon>0$ can occur. A coarse lower bound is:
$$
\hat\varepsilon \gtrsim 1-\exp\big(-\gamma,\Theta(\Delta)\big).
$$
Here $\Theta(\Delta)$ measures “opportunities for order variation” within window $\Delta$ (e.g., expected number of candidate concurrent pairs or non-commutative pairs), and $\gamma$ aggregates sensitivity from non-commutativity to outcome divergence (including integration structure and detector characteristics).

---

# 12. Falsifiability conditions (Falsifiability-first)

A framework is scientifically useful insofar as it can be refuted [@popperLogicScientificDiscovery1959]. Refutation tests should fix a time window (e.g., 4-week moving average; or N-day pre/post intervention windows) and can be implemented via monotonicity tests, change-point detection [@baiEstimatingTestingLinear1998], or distributional distances (e.g., Mann–Kendall; segmented regression/changepoint; KS distance). This paper does not fix a single method; it specifies minimal requirements for falsifiability.

| ID | Target hypothesis                                                      | Observables (log metrics)                       | Example refutation criterion                                                                          |
| -- | ---------------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| F1 | Closed-loop dominance / non-monotone boundary (Prop 1)                 | $\rho,r$ vs intervention $a$                    | $r$ does not increase and $\rho$ improves monotonically as $a$ rises                                  |
| F2 | CRS staleness drives failure                                           | $\Pi$ and CRS-failure proxies                   | CRS-failure proxies do not worsen even with sustained $\Pi>1$                                         |
| F3 | VR staleness drives failure                                            | $\Psi$ and recipe-failure proxies               | recipe-failure proxies do not worsen even with sustained $\Psi>1$                                     |
| F4 | Resolution improves downstream outcomes                                | $\hat R$ vs $r,1-\hat p_\Delta,\hat\varepsilon$ | improvements do not occur despite $\hat R\uparrow$                                                    |
| F5 | Detector false positives worsen short-term load                        | retry proxies vs $\rho$                         | $\rho$ does not worsen despite increased retries                                                      |
| F6 | Non-commutativity × strictness implies serialization pressure (Prop 2) | $\hat p_\Delta,\hat\varepsilon$                 | $\hat\varepsilon$ does not worsen under concurrent finalization even in strict/non-commutative region |
| F7 | Exploration share improves downstream outcomes                         | $\hat s$ vs $r,1-\hat p_\Delta,\hat\varepsilon$ | no improvement despite $\hat s\uparrow$                                                               |
| F8 | Concurrency pressure raises $\rho$                                     | $\kappa$ vs $\rho$                              | $\rho$ does not systematically rise as $\kappa\uparrow$                                               |

---

# 13. Minimal estimation & intervention design (Identifiability-first)

## 13.1 Minimal estimation set

$$
{\rho(t),\Pi(t),\Psi(t),r(t),\hat p_\Delta(t),\hat\varepsilon(t),\text{detector proxy},\hat s(t),\hat R(t),\kappa(t),\chi(t)}
$$
plus proxies relevant to $g_{\mathrm{CRS}}$ and $g_{\mathrm{VR}}$.

## 13.2 Treat RP bandwidths as estimable service rates

RP bandwidths $C_{\mathrm{RP,*}}(t)$ are not normative constants; they are estimated as service rates from observed throughput and waiting-time/cycle-time distributions (including WIP proxies), and treated as time-varying effective capacities. The same applies to $C_{\mathrm{RP,CRS}}$ and $C_{\mathrm{RP,VR}}$ using CRS/VR update event volumes and lead-time distributions.

**Minimal estimation sketch**:
(1) Extract low-load periods (sufficiently small $\rho$); use an upper quantile (e.g., 90th percentile) of observed finalization throughput as a proxy for $C_{\mathrm{RP,fin}}$.
(2) Alternatively, reference Little’s law using WIP proxy $L$ and cycle time to back out a service rate consistent with observed $\lambda_{\text{eff}}$ and $W$ (and analogously for CRS/VR update streams).

## 13.3 “No backlog” environments

Even without explicit backlog artifacts, $\rho$ can be estimated from waiting times and cycle-time distributions; $\Pi$ and $\Psi$ can be estimated from event densities and lead-time distributions of CRS/VR updates.

## 13.4 Intervention axes (examples)

* Generation pressure: $\lambda_{\text{new}}$, $L$
* Exploration & resolution: $\hat s$, $\hat R$
* Detector improvement & recipe updates: detector proxies; $\lambda_{\mathrm{VR}}$
* Commutativization: improving $\hat p_\Delta$
* Reproducibility requirement and windowing: $\varepsilon_{\max}$, fixed $\Delta$

---

# 14. Limitations

* Proxy validity is context-dependent and requires fixed definitions and validation.
* $\rho,\Pi,\Psi$ are first-order approximations and do not fully capture multi-stage bottlenecks or batching.
* Phase boundaries are bands, not sharp lines, due to lag, transients, and exogenous shocks.
* Many practical interpretations assume current institutions where RP is typically human; if non-human entities institutionally accept irreversible-loss exposure, bottlenecks and phase boundaries may change qualitatively.
* The paper does not prescribe value judgments; it provides branching conditions and observability.
* Software evolution pressures [@lehmanProgramsLifeCycles1980] and modularization choices [@parnasCriteriaBeUsed1972a] affect how CRS/VR staleness accumulates; these dynamics are not modeled explicitly.

---

# 15. Conclusion

This paper presents a portable observational language for phase transitions in human–AI collaborative development. The core is to treat (i) finalization load $\rho$ and (ii) dual CP staleness pressures $\Pi$ (CRS) and $\Psi$ (VR) as primary axes, and connect them to measurable proxies for non-commutativity $\hat p_\Delta$, reproducibility loss $\hat\varepsilon$, detector behavior, exploration share $\hat s$, CRS resolution $\hat R$, concurrency pressure $\kappa$, and strictness summary $\chi$. Phase transitions are defined observationally as distribution-shape changes, and falsifiability conditions specify minimal time-window and test-form requirements. The framework aims to prevent premature heuristic short-circuits and to map diverse futures as movements of phase boundaries.

---

# Glossary

* **CP**: Control Plane (meta layer)
* **DP**: Data Plane (object layer)
* **CRS**: correctness reference system (normative/semantic reference defining correctness)
* **VR**: verification recipes (operational detectors mapping CRS to judgments)
* **RC**: rules/commands (constraints and recovery standards)
* **verification gate (recipe)**: a detector recipe
* **verification artifacts**: tests/analyses/audit scripts (DP-side artifacts)
* **finalization event**: an event after which rollback is materially constrained

**RP bandwidths (notation fixed)**

* $C_{\mathrm{RP,fin}}(t)$: finalization bandwidth (estimated as a service rate)
* $C_{\mathrm{RP,CRS}}(t)$: CRS maintenance bandwidth (service rate)
* $C_{\mathrm{RP,VR}}(t)$: VR maintenance bandwidth (service rate)

**Staleness pressures**

* $\Pi=\lambda_{\mathrm{CRS}} w_{\mathrm{CRS}}/C_{\mathrm{RP,CRS}}$
* $\Psi=\lambda_{\mathrm{VR}} w_{\mathrm{VR}}/C_{\mathrm{RP,VR}}$
* $g_{\mathrm{CRS}}(\cdot)$, $g_{\mathrm{VR}}(\cdot)$: induced-demand mechanisms

**Non-commutativity and reproducibility**

* $\Delta$: fixed concurrency window
* $\hat p_\Delta$: commutativity proxy
* $\hat\varepsilon$: reproducibility-loss proxy
* $\varepsilon_{\max}$: reproducibility SLO

**Exploration and resolution**

* $\hat s$: exploration share
* $\hat R$: CRS resolution proxy

**Concurrency pressure**

* $\lambda_{\text{new}}$: new arrival rate
* $L$: concurrency window proxy
* $\kappa=\lambda_{\text{new}}L/C_{\mathrm{RP,fin}}$: concurrency pressure

**Strictness summary**

* $\chi=f(1-\hat p_\Delta,\varepsilon_{\max};\Delta)$, instantiated as $(1-\hat p_\Delta)/\varepsilon_{\max}$

**Auxiliary terms for Proposition 2**

* $\Theta(\Delta)$: opportunities for order variation within window $\Delta$
* $\gamma$: sensitivity from non-commutativity to outcome divergence

---

# Conflict of Interest

The author declares no conflict of interest.

---

# References
