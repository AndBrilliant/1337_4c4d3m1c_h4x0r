# Dykhne 1971 — Conductivity of a 2D two-phase system

## Reference
A. M. Dykhne, *Conductivity of a two-dimensional two-phase system*, **Sov. Phys. JETP 32 (1971) 63–65** [original Russian: Zh. Eksp. Teor. Fiz. **59** (1970) 110–115]; English translation by P. J. Shepherd. (No arXiv; Soviet-era journal.)

## Source
- Research report §5 (Geometric means in effective-medium theory), tier ★ — flagged as "the primary citation establishing that for an isotropic 2D two-phase composite with equal volume fractions, $\sigma_{\rm eff} = \sqrt{\sigma_1\sigma_2}$."

## Beyond-abstract summary
A three-page note giving an exact result for the effective DC conductivity of a 2D two-phase composite. The argument uses the *duality transformation* in 2D: under the rotation $\mathbf{j} \to \hat z \times \mathbf{E}$, $\mathbf{E} \to \hat z \times \mathbf{j}$, the conductivity $\sigma$ maps to its inverse-times-determinant $\rho = 1/\sigma$, exchanging the two phases. For an isotropic random two-phase composite with equal volume fractions of phases having conductivities $\sigma_1$ and $\sigma_2$, the duality fixes
$$\sigma_{\rm eff}^2 = \sigma_1 \sigma_2 \implies \sigma_{\rm eff} = \sqrt{\sigma_1\sigma_2}.$$
This is an *exact* result valid in any 2D isotropic geometry — the geometric mean is forced by self-duality of the random tessellation, not by any specific microstructural assumption. The same theorem had been derived earlier by Matheron (1967) in the porous-media literature; the combined result is now called the Matheron–Dykhne theorem.

## Sections / contents
- Statement of the 2D duality $\mathbf{j} \leftrightarrow \hat z \times \mathbf{E}$.
- Application to a statistically self-dual two-phase medium with equal volume fractions.
- Derivation $\sigma_{\rm eff} = \sqrt{\sigma_1\sigma_2}$.
- Remark on anisotropic generalizations.

## Use in the F-identity manuscript
Cited as the CM canonical example of a *geometric mean* being the exact physical answer for an effective-medium parameter. The F-identity manuscript's cascade uses two geometric-mean relations:
- $m_s^2 = \mu_\star \cdot m_d$ (Eq. 13 in the paper) — $m_s$ is the geometric mean of $\mu_\star$ and $m_d$.
- $m_u^2 = m_d \cdot 2m_e$ (Eq. 14) — $m_u$ is the geometric mean of $m_d$ and the pair-production threshold.

Dykhne 1971 provides the CM precedent that "geometric mean = exact effective answer" is not an arbitrary algebraic choice but a structural consequence of duality. The F-identity manuscript does not argue an explicit duality structure underlying the quark cascade — but if a referee asks "why a geometric mean rather than arithmetic or harmonic," Dykhne is the canonical citation.

## Sub-citations (one level down)

**Caveat: Sov. Phys. JETP 32 (1971) 63 is a three-page note from a Soviet-era journal; the bibliography of such notes is typically 5–10 entries. The sub-citation list below is reconstructed from training knowledge of the Soviet 2D-conductivity literature and the standard secondary literature citing Dykhne. Mark as *not web-verified*.**

1. **G. Matheron**, *Éléments pour une Théorie des Milieux Poreux* (Masson, Paris, 1967), 166 pp. — *Topic:* the same 2D geometric-mean theorem derived earlier in the porous-media context (the "Matheron conjecture"). *Role:* potentially the prior-art citation; jointly the theorem is named "Matheron–Dykhne."
2. **L. D. Landau and E. M. Lifshitz**, *Electrodynamics of Continuous Media*, §9 (Pergamon, 1960). — *Topic:* standard treatment of duality in 2D electrostatics and the divergence-free / curl-free structure. *Role:* foundational textbook reference Dykhne would cite as the basis for the 2D duality transformation.
3. **A. M. Dykhne**, earlier Soviet papers on conductivity of inhomogeneous media (Sov. Phys. JETP 1967–70 range). — *Topic:* author's prior work on related problems. *Role:* self-citation.
4. **J. B. Keller**, *A theorem on the conductivity of a composite medium*, J. Math. Phys. **5** (1964) 548. — *Topic:* the Keller reciprocity theorem for 2D conductivity. *Role:* a related duality result; commonly cited alongside Dykhne in the Western secondary literature, although citing Keller from a 1970 Soviet paper is plausible but not certain.
5. Possibly: **B. Y. Balagurov**, *Reciprocity relations in a two-dimensional percolation theory*, Sov. Phys. JETP or related. — *Topic:* 2D random-medium duality. *Role:* contemporary related work.

*(End of training-knowledge reconstruction. Verification requires the Soviet Physics JETP scan, which is in physical archives.)*

## Status
Sov. Phys. JETP **32** (1971) 63, peer-reviewed (translation of Zh. Eksp. Teor. Fiz. 59 (1970) 110). Foundational CM theorem; standard reference in the effective-medium literature (Milton 2002, *Theory of Composites*, gives the full modern treatment).

**Build note (2026-05-19):** Sub-citations above are reconstructed from training knowledge of the Soviet 2D-conductivity literature; verification against the original 1970 Russian text or 1971 English translation is pending. Modern secondary references — Milton (2002), Hashin–Shtrikman (1962/63) — are well-verified.

## Citation verification

- **Verdict:** `FLAG`
- **Checked:** 2026-05-23 12:58  (urllib)
- **Source URL:** (none)
- **Rationale:**
  - insufficient deterministic signal — bib lacks DOI and arXiv ID
