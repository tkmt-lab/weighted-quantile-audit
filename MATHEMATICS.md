# Certificate argument

Let the distinct sorted observations be v1<…<vm, with positive aggregated masses a1,…,am. Let Sj=Σ(i≤j)ai, S0=0, W=Sm and t=pW, where 0<p<1. Strict positivity makes Sj strictly increasing and 0<t<W. There is exactly one first j with t≤Sj.

If S(j−1)<t<Sj, boundary-average and inverted CDF both return vj. If t=Sj, j<m because t<W; boundary-average returns (vj+v(j+1))/2 and inverted CDF returns vj. This specifies both definitions, including the convention at a boundary. It follows the statsmodels documented convention; full SAS compatibility is not claimed.

The producer sorts/aggregates exact Fraction values. The separate checker instead recomputes L=Σ(wi:xi<left), U=Σ(wi:xi≤left), W and t from the original observations. It requires left to occur, L<t<U for a point, or t=U and the next distinct support right for a tie. It then verifies the formula for value. Hence every accepted mathematical certificate satisfies its stated definition; completeness of arbitrary library behavior is a different claim. The argument is informal mathematics, not machine-checked formal proof.

The checker also binds each nominal rational to its actual binary64 conversion and saved hex, then repeats the mathematical verification for this binary input. Comparing the two exact values isolates input conversion from implementation behavior. Comparing actual output with the correctly rounded exact binary answer permits ordinary final rounding. Comparing two exact definitions on the same binary input isolates the definition axis.

Multiplication of every weight by an exact c>0 multiplies L,U,t,W by c. It preserves all equalities/inequalities and both exact answers. In the saved two-point example, gap=2^-34 for weights[1,1] and gap=2^-33 for weights[2,2]. The former is below the binary64 representation of 1e-10 and the latter above it. Both targets and cumulative sums are exact, so the observed mean only in the first case is a fixed-tolerance boundary witness.

Reproduced float diagnostics are checked internally by the standalone checker. Their relation to the actual pandas group sums and statsmodels return is tested by a separate pinned replay. The standalone checker deliberately does not treat environment strings or a producer's own verification receipt as proof that a library was run. Source hashes and version checks support reproducibility, not cryptographic attestation of an execution.
