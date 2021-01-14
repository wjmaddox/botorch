#! /usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

r"""
Multi-objective optimization benchmark problems.

References

.. [Deb2005dtlz]
    K. Deb, L. Thiele, M. Laumanns, E. Zitzler, A. Abraham, L. Jain, R. Goldberg.
    "Scalable test problems for evolutionary multi-objective optimization"
    in Evolutionary Multiobjective Optimization, London, U.K.: Springer-Verlag,
    pp. 105-145, 2005.

.. [GarridoMerchan2020]
    E. C. Garrido-Merch ́an and D. Hern ́andez-Lobato. Parallel Predictive Entropy
    Search for Multi-objective Bayesian Optimization with Constraints.
    arXiv e-prints, arXiv:2004.00601, Apr. 2020.

.. [Gelbart2014]
    Michael A. Gelbart, Jasper Snoek, and Ryan P. Adams. 2014. Bayesian
    optimization with unknown constraints. In Proceedings of the Thirtieth
    Conference on Uncertainty in Artificial Intelligence (UAI’14).
    AUAI Press, Arlington, Virginia, USA, 250–259.

.. [Oszycka1995]
    A. Osyczka, S. Kundu. 1995. A new method to solve generalized multicriteria 
    optimization problems using the simple genetic algorithm. In Structural
    Optimization 10. 94–99.
    
.. [Tanabe2020]
    Ryoji Tanabe, Hisao Ishibuchi, An easy-to-use real-world multi-objective
    optimization problem suite, Applied Soft Computing,Volume 89, 2020.

.. [Yang2019a]
    K. Yang, M. Emmerich, A. Deutz, and T. Bäck. 2019.
    "Multi-Objective Bayesian Global Optimization using expected hypervolume
    improvement gradient" in Swarm and evolutionary computation 44, pp. 945--956,
    2019.

.. [Zitzler2000]
    E. Zitzler, K. Deb, and L. Thiele, “Comparison of multiobjective
    evolutionary algorithms: Empirical results,” Evol. Comput., vol. 8, no. 2,
    pp. 173–195, 2000.
"""

from __future__ import annotations

import math
from typing import Optional

import torch
from botorch.test_functions.base import (
    ConstrainedBaseTestProblem,
    MultiObjectiveTestProblem,
)
from botorch.test_functions.synthetic import Branin
from botorch.utils.sampling import sample_hypersphere, sample_simplex
from botorch.utils.transforms import unnormalize
from scipy.special import gamma
from torch import Tensor


class BraninCurrin(MultiObjectiveTestProblem):
    r"""Two objective problem composed of the Branin and Currin functions.

    Branin (rescaled):

        f(x) = (
        15*x_1 - 5.1 * (15 * x_0 - 5) ** 2 / (4 * pi ** 2) + 5 * (15 * x_0 - 5)
        / pi - 5
        ) ** 2 + (10 - 10 / (8 * pi)) * cos(15 * x_0 - 5))

    Currin:

        f(x) = (1 - exp(-1 / (2 * x_1))) * (
        2300 * x_0 ** 3 + 1900 * x_0 ** 2 + 2092 * x_0 + 60
        ) / 100 * x_0 ** 3 + 500 * x_0 ** 2 + 4 * x_0 + 20

    """

    dim = 2
    num_objectives = 2
    _bounds = [(0.0, 1.0), (0.0, 1.0)]
    _ref_point = [18.0, 6.0]
    _max_hv = 59.36011874867746  # this is approximated using NSGA-II

    def __init__(self, noise_std: Optional[float] = None, negate: bool = False) -> None:
        r"""Constructor for Branin-Currin.

        Args:
            noise_std: Standard deviation of the observation noise.
            negate: If True, negate the objectives.
        """
        super().__init__(noise_std=noise_std, negate=negate)
        self._branin = Branin()

    def _rescaled_branin(self, X: Tensor) -> Tensor:
        # return to Branin bounds
        x_0 = 15 * X[..., 0] - 5
        x_1 = 15 * X[..., 1]
        return self._branin(torch.stack([x_0, x_1], dim=-1))

    @staticmethod
    def _currin(X: Tensor) -> Tensor:
        x_0 = X[..., 0]
        x_1 = X[..., 1]
        factor1 = 1 - torch.exp(-1 / (2 * x_1))
        numer = 2300 * x_0.pow(3) + 1900 * x_0.pow(2) + 2092 * x_0 + 60
        denom = 100 * x_0.pow(3) + 500 * x_0.pow(2) + 4 * x_0 + 20
        return factor1 * numer / denom

    def evaluate_true(self, X: Tensor) -> Tensor:
        # branin rescaled with inputsto [0,1]^2
        branin = self._rescaled_branin(X=X)
        currin = self._currin(X=X)
        return torch.stack([branin, currin], dim=-1)


class DTLZ(MultiObjectiveTestProblem):
    r"""Base class for DTLZ problems.

    See [Deb2005dtlz]_ for more details on DTLZ.
    """

    def __init__(
        self,
        dim: int,
        num_objectives: int = 2,
        noise_std: Optional[float] = None,
        negate: bool = False,
    ) -> None:
        if dim <= num_objectives:
            raise ValueError(
                f"dim must be > num_objectives, but got {dim} and {num_objectives}"
            )
        self.num_objectives = num_objectives
        self.dim = dim
        self.k = self.dim - self.num_objectives + 1
        self._bounds = [(0.0, 1.0) for _ in range(self.dim)]
        self._ref_point = [self._ref_val for _ in range(num_objectives)]
        super().__init__(noise_std=noise_std, negate=negate)


class DTLZ1(DTLZ):
    r"""DLTZ1 test problem.

    d-dimensional problem evaluated on `[0, 1]^d`:

        f_0(x) = 0.5 * x_0 * (1 + g(x))
        f_1(x) = 0.5 * (1 - x_0) * (1 + g(x))
        g(x) = 100 * \sum_{i=m}^{n-1} (
        k + (x_i - 0.5)^2 - cos(20 * pi * (x_i - 0.5))
        )

    where k = n - m + 1.

    The pareto front is given by the line (or hyperplane) \sum_i f_i(x) = 0.5.
    The goal is to minimize both objectives. The reference point comes from [Yang2019]_.
    """

    _ref_val = 400.0

    @property
    def _max_hv(self) -> float:
        return self._ref_val ** self.num_objectives - 1 / 2 ** self.num_objectives

    def evaluate_true(self, X: Tensor) -> Tensor:
        X_m = X[..., -self.k :]
        X_m_minus_half = X_m - 0.5
        sum_term = (
            X_m_minus_half.pow(2) - torch.cos(20 * math.pi * X_m_minus_half)
        ).sum(dim=-1)
        g_X_m = 100 * (self.k + sum_term)
        g_X_m_term = 0.5 * (1 + g_X_m)
        fs = []
        for i in range(self.num_objectives):
            idx = self.num_objectives - 1 - i
            f_i = g_X_m_term * X[..., :idx].prod(dim=-1)
            if i > 0:
                f_i *= 1 - X[..., idx]
            fs.append(f_i)
        return torch.stack(fs, dim=-1)

    def gen_pareto_front(self, n: int) -> Tensor:
        r"""Generate `n` pareto optimal points.

        The pareto points randomly sampled from the hyperplane sum_i f(x_i) = 0.5.
        """
        f_X = 0.5 * sample_simplex(
            n=n,
            d=self.num_objectives,
            qmc=True,
            dtype=self.ref_point.dtype,
            device=self.ref_point.device,
        )
        if self.negate:
            f_X *= -1
        return f_X


class DTLZ2(DTLZ):
    r"""DLTZ2 test problem.

    d-dimensional problem evaluated on `[0, 1]^d`:

        f_0(x) = (1 + g(x)) * cos(x_0 * pi / 2)
        f_1(x) = (1 + g(x)) * sin(x_0 * pi / 2)
        g(x) = \sum_{i=m}^{n-1} (x_i - 0.5)^2

    The pareto front is given by the unit hypersphere \sum{i} f_i^2 = 1.
    Note: the pareto front is completely concave. The goal is to minimize
    both objectives.
    """

    _ref_val = 1.1

    @property
    def _max_hv(self) -> float:
        # hypercube - volume of hypersphere in R^n such that all coordinates are
        # positive
        hypercube_vol = self._ref_val ** self.num_objectives
        pos_hypersphere_vol = (
            math.pi ** (self.num_objectives / 2)
            / gamma(self.num_objectives / 2 + 1)
            / 2 ** self.num_objectives
        )
        return hypercube_vol - pos_hypersphere_vol

    def evaluate_true(self, X: Tensor) -> Tensor:
        X_m = X[..., -self.k :]
        g_X = (X_m - 0.5).pow(2).sum(dim=-1)
        g_X_plus1 = 1 + g_X
        fs = []
        pi_over_2 = math.pi / 2
        for i in range(self.num_objectives):
            idx = self.num_objectives - 1 - i
            f_i = g_X_plus1.clone()
            f_i *= torch.cos(X[..., :idx] * pi_over_2).prod(dim=-1)
            if i > 0:
                f_i *= torch.sin(X[..., idx] * pi_over_2)
            fs.append(f_i)
        return torch.stack(fs, dim=-1)

    def gen_pareto_front(self, n: int) -> Tensor:
        r"""Generate `n` pareto optimal points.

        The pareto points are randomly sampled from the hypersphere's
        positive section.
        """
        f_X = sample_hypersphere(
            n=n,
            d=self.num_objectives,
            dtype=self.ref_point.dtype,
            device=self.ref_point.device,
            qmc=True,
        ).abs()
        if self.negate:
            f_X *= -1
        return f_X


class VehicleSafety(MultiObjectiveTestProblem):
    r"""Optimize Vehicle crash-worthiness.

    See [Tanabe2020]_ for details.

    The reference point is 1.1 * the nadir point from
    approximate front provided by [Tanabe2020]_.

    The maximum hypervolume is computed using the approximate
    pareto front from [Tanabe2020]_.
    """

    _ref_point = [1864.72022, 11.81993945, 0.2903999384]
    _max_hv = 246.81607081187002
    _bounds = [(1.0, 3.0)] * 5
    dim = 5
    num_objectives = 3

    def evaluate_true(self, X: Tensor) -> Tensor:
        X1, X2, X3, X4, X5 = torch.split(X, 1, -1)
        f1 = (
            1640.2823
            + 2.3573285 * X1
            + 2.3220035 * X2
            + 4.5688768 * X3
            + 7.7213633 * X4
            + 4.4559504 * X5
        )
        f2 = (
            6.5856
            + 1.15 * X1
            - 1.0427 * X2
            + 0.9738 * X3
            + 0.8364 * X4
            - 0.3695 * X1 * X4
            + 0.0861 * X1 * X5
            + 0.3628 * X2 * X4
            - 0.1106 * X1.pow(2)
            - 0.3437 * X3.pow(2)
            + 0.1764 * X4.pow(2)
        )
        f3 = (
            -0.0551
            + 0.0181 * X1
            + 0.1024 * X2
            + 0.0421 * X3
            - 0.0073 * X1 * X2
            + 0.024 * X2 * X3
            - 0.0118 * X2 * X4
            - 0.0204 * X3 * X4
            - 0.008 * X3 * X5
            - 0.0241 * X2.pow(2)
            + 0.0109 * X4.pow(2)
        )
        f_X = torch.cat([f1, f2, f3], dim=-1)
        return f_X


class ZDT(MultiObjectiveTestProblem):
    r"""Base class for ZDT problems.

    See [Zitzler2000]_ for more details on ZDT.
    """

    _ref_point = [11.0, 11.0]

    def __init__(
        self,
        dim: int,
        num_objectives: int = 2,
        noise_std: Optional[float] = None,
        negate: bool = False,
    ) -> None:
        if num_objectives != 2:
            raise NotImplementedError(
                f"{type(self).__name__} currently only supports 2 objectives."
            )
        if dim < num_objectives:
            raise ValueError(
                f"dim must be >= num_objectives, but got {dim} and {num_objectives}"
            )
        self.num_objectives = num_objectives
        self.dim = dim
        self._bounds = [(0.0, 1.0) for _ in range(self.dim)]
        super().__init__(noise_std=noise_std, negate=negate)

    @staticmethod
    def _g(X: Tensor) -> Tensor:
        return 1 + 9 * X[..., 1:].mean(dim=-1)


class ZDT1(ZDT):
    r"""ZDT1 test problem.

    d-dimensional problem evaluated on `[0, 1]^d`:

        f_0(x) = x_0
        f_1(x) = g(x) * (1 - sqrt(x_0 / g(x))
        g(x) = 1 + 9 / (d - 1) * \sum_{i=1}^{d-1} x_i

    The reference point comes from [Yang2019a]_.

    The pareto front is convex.
    """

    _max_hv = 120 + 2 / 3

    def evaluate_true(self, X: Tensor) -> Tensor:
        f_0 = X[..., 0]
        g = self._g(X=X)
        f_1 = g * (1 - (f_0 / g).sqrt())
        return torch.stack([f_0, f_1], dim=-1)

    def gen_pareto_front(self, n: int) -> Tensor:
        f_0 = torch.linspace(
            0, 1, n, dtype=self.bounds.dtype, device=self.bounds.device
        )
        f_1 = 1 - f_0.sqrt()
        f_X = torch.stack([f_0, f_1], dim=-1)
        if self.negate:
            f_X *= -1
        return f_X


class ZDT2(ZDT):
    r"""ZDT2 test problem.

    d-dimensional problem evaluated on `[0, 1]^d`:

        f_0(x) = x_0
        f_1(x) = g(x) * (1 - (x_0 / g(x))^2)
        g(x) = 1 + 9 / (d - 1) * \sum_{i=1}^{d-1} x_i

    The reference point comes from [Yang2019a]_.

    The pareto front is concave.
    """

    _max_hv = 120 + 1 / 3

    def evaluate_true(self, X: Tensor) -> Tensor:
        f_0 = X[..., 0]
        g = self._g(X=X)
        f_1 = g * (1 - (f_0 / g).pow(2))
        return torch.stack([f_0, f_1], dim=-1)

    def gen_pareto_front(self, n: int) -> Tensor:
        f_0 = torch.linspace(
            0, 1, n, dtype=self.bounds.dtype, device=self.bounds.device
        )
        f_1 = 1 - f_0.pow(2)
        f_X = torch.stack([f_0, f_1], dim=-1)
        if self.negate:
            f_X *= -1
        return f_X


class ZDT3(ZDT):
    r"""ZDT3 test problem.

    d-dimensional problem evaluated on `[0, 1]^d`:

        f_0(x) = x_0
        f_1(x) = 1 - sqrt(x_0 / g(x)) - x_0 / g * sin(10 * pi * x_0)
        g(x) = 1 + 9 / (d - 1) * \sum_{i=1}^{d-1} x_i

    The reference point comes from [Yang2019a]_.

    The pareto front consists of several discontinuous convex parts.
    """

    _max_hv = 128.77811613069076060
    _parts = [
        # this interval includes both end points
        [0, 0.0830015349],
        # this interval includes only the right end points
        [0.1822287280, 0.2577623634],
        [0.4093136748, 0.4538821041],
        [0.6183967944, 0.6525117038],
        [0.8233317983, 0.8518328654],
    ]
    # nugget to make sure linspace returns elements within the specified range
    _eps = 1e-6

    def evaluate_true(self, X: Tensor) -> Tensor:
        f_0 = X[..., 0]
        g = self._g(X=X)
        f_1 = 1 - (f_0 / g).sqrt() - f_0 / g * torch.sin(10 * math.pi * f_0)
        return torch.stack([f_0, f_1], dim=-1)

    def gen_pareto_front(self, n: int) -> Tensor:
        n_parts = len(self._parts)
        n_per_part = torch.full(
            torch.Size([n_parts]),
            n // n_parts,
            dtype=torch.long,
            device=self.bounds.device,
        )
        left_over = n % n_parts
        n_per_part[:left_over] += 1
        f_0s = []
        for i, p in enumerate(self._parts):
            left, right = p
            f_0s.append(
                torch.linspace(
                    left + self._eps,
                    right - self._eps,
                    n_per_part[i],
                    dtype=self.bounds.dtype,
                    device=self.bounds.device,
                )
            )
        f_0 = torch.cat(f_0s, dim=0)
        f_1 = 1 - f_0.sqrt() - f_0 * torch.sin(10 * math.pi * f_0)
        f_X = torch.stack([f_0, f_1], dim=-1)
        if self.negate:
            f_X *= -1
        return f_X


# ------ Constrained Multi-Objective Test Problems ----- #


class BNH(MultiObjectiveTestProblem, ConstrainedBaseTestProblem):
    r"""The constrained BNH problem.

    See [GarridoMerchan2020]_ for more details on this problem. Note that this is a
    minimization problem.
    """

    dim = 2
    num_objectives = 2
    num_constraints = 2
    _bounds = [(0.0, 5.0), (0.0, 3.0)]
    _ref_point = [0.0, 0.0]  # TODO: Determine proper reference point

    def evaluate_true(self, X: Tensor) -> Tensor:
        return torch.stack(
            [4.0 * (X ** 2).sum(dim=-1), ((X - 5.0) ** 2).sum(dim=-1)], dim=-1
        )

    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        c1 = 25.0 - (X[..., 0] - 5.0) ** 2 - X[..., 1] ** 2
        c2 = (X[..., 0] - 8.0) ** 2 + (X[..., 1] + 3.0) ** 2 - 7.7
        return torch.stack([c1, c2], dim=-1)


class SRN(MultiObjectiveTestProblem, ConstrainedBaseTestProblem):
    r"""The constrained SRN problem.

    See [GarridoMerchan2020]_ for more details on this problem. Note that this is a
    minimization problem.
    """

    dim = 2
    num_objectives = 2
    num_constraints = 2
    _bounds = [(-20.0, 20.0), (-20.0, 20.0)]
    _ref_point = [0.0, 0.0]  # TODO: Determine proper reference point

    def evaluate_true(self, X: Tensor) -> Tensor:
        obj1 = 2.0 + ((X - 2.0) ** 2).sum(dim=-1)
        obj2 = 9.0 * X[..., 0] - (X[..., 1] - 1.0) ** 2
        return torch.stack([obj1, obj2], dim=-1)

    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        c1 = 225.0 - ((X ** 2) ** 2).sum(dim=-1)
        c2 = -10.0 - X[..., 0] + 3 * X[..., 1]
        return torch.stack([c1, c2], dim=-1)


class CONSTR(MultiObjectiveTestProblem, ConstrainedBaseTestProblem):
    r"""The constrained CONSTR problem.

    See [GarridoMerchan2020]_ for more details on this problem. Note that this is a
    minimization problem.
    """

    dim = 2
    num_objectives = 2
    num_constraints = 2
    _bounds = [(0.1, 10.0), (0.0, 5.0)]
    _ref_point = [10.0, 10.0]

    def evaluate_true(self, X: Tensor) -> Tensor:
        obj1 = X[..., 0]
        obj2 = (1.0 + X[..., 1]) / X[..., 0]
        return torch.stack([obj1, obj2], dim=-1)

    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        c1 = 9.0 * X[..., 0] + X[..., 1] - 6.0
        c2 = 9.0 * X[..., 0] - X[..., 1] - 1.0
        return torch.stack([c1, c2], dim=-1)


class ConstrainedBraninCurrin(BraninCurrin, ConstrainedBaseTestProblem):
    r"""Constrained Branin Currin Function.

    This uses the disk constraint from [Gelbart2014]_.
    """

    dim = 2
    num_objectives = 2
    num_constraints = 1
    _bounds = [(0.0, 1.0), (0.0, 1.0)]
    _con_bounds = [(-5.0, 10.0), (0.0, 15.0)]
    _ref_point = [80.0, 12.0]
    _max_hv = 608.4004237022673  # from NSGA-II with 90k evaluations

    def __init__(self, noise_std: Optional[float] = None, negate: bool = False) -> None:
        super().__init__(noise_std=noise_std, negate=negate)
        con_bounds = torch.tensor(self._con_bounds, dtype=torch.float).transpose(-1, -2)
        self.register_buffer("con_bounds", con_bounds)

    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        X_tf = unnormalize(X, self.con_bounds)
        return 50 - (X_tf[..., 0:1] - 2.5).pow(2) - (X_tf[..., 1:2] - 7.5).pow(2)


class C2DTLZ2(DTLZ2, ConstrainedBaseTestProblem):

    num_constraints = 1
    _r = 0.2
    # approximate from nsga-ii, TODO: replace with analytic
    _max_hv = 0.3996406303723544

    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        if X.ndim > 2:
            raise NotImplementedError("Batch X is not supported.")
        f_X = self.evaluate_true(X)
        term1 = (f_X - 1).pow(2)
        mask = ~(torch.eye(f_X.shape[-1], device=f_X.device).bool())
        indices = torch.arange(f_X.shape[1], device=f_X.device).repeat(f_X.shape[1], 1)
        indexer = indices[mask].view(f_X.shape[1], f_X.shape[-1] - 1)
        term2_inner = (
            f_X.unsqueeze(1)
            .expand(f_X.shape[0], f_X.shape[-1], f_X.shape[-1])
            .gather(dim=-1, index=indexer.repeat(f_X.shape[0], 1, 1))
        )
        term2 = (term2_inner.pow(2) - self._r ** 2).sum(dim=-1)
        min1 = (term1 + term2).min(dim=-1).values
        min2 = ((f_X - 1 / math.sqrt(f_X.shape[-1])).pow(2) - self._r ** 2).sum(dim=-1)
        return -torch.min(min1, min2).unsqueeze(-1)
    
class OSY(MultiObjectiveTestProblem, ConstrainedBaseTestProblem):
    r""" 
    The OSY test problem from [Oszycka1995]. 
    Implementation from https://github.com/msu-coinlab/pymoo/blob/master/pymoo/problems/multi/osy.py
    
    This implementation assumes minimization.
    """
    
    dim = 6
    num_constraints = 6
    num_objectives = 2
    _bounds = [(0.0, 10.0), (0.0, 10.0), (1.0, 5.0), (0.0, 6.0), (1.0, 5.0), (0.0, 10.0)]
    _ref_point = [-75.0, 75.0]
    
    def __init__(
        self,
        dim: int = 6,
        num_objectives: int = 2,
        noise_std: Optional[float] = None,
        negate: bool = True,
    ) -> None:
        super().__init__(noise_std=noise_std, negate=negate)
        
    def evaluate_true(self, X: Tensor) -> Tensor:
        f1 = - (25 * (X[..., 0] - 2) ** 2 + (X[..., 1] - 2) ** 2 + (X[..., 2] - 1) ** 2 + (X[..., 3] - 4) ** 2 + (
                    X[..., 4] - 1) ** 2)
        f2 = (X**2).sum(-1)
        return torch.stack([f1, f2], dim=-1)

    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        g1 = (X[..., 0] + X[..., 1] - 2.0)
        g2 = (6.0 - X[..., 0] - X[..., 1])
        g3 = (2.0 - X[..., 1] + X[..., 0])
        g4 = (2.0 - X[..., 0] + 3.0 * X[..., 1])
        g5 = (4.0 - (X[..., 2] - 3.0) ** 2 - X[..., 3])
        g6 = ((X[..., 4] - 3.0) ** 2 + X[..., 5] - 4.0)
        return torch.stack([g1, g2, g3, g4, g5, g6], dim=-1)
    
class SwitchRipple(MultiObjectiveTestProblem, ConstrainedBaseTestProblem):
    r""" 
    Ripple problem from :
    implementation taken via https://github.com/vpicheny/GPGame/blob/master/example/ripple_test.R
    """
    dim = 6
    num_objectives = dim - 3
    _bounds = [(0.000110815602836879, 0.000221631205673759), 
               (7.83532027529331e-06, 0.000783532027529331), 
               (1.29313391262165e-06, 0.000783532027529331), 
               (1.29313391262165e-06, 6.46566956310825e-05),
               (1.29313391262165e-06, 6.46566956310825e-05),
               # (1.29313391262165e-06, 6.46566956310825e-05),
               # (1.29313391262165e-06, 6.46566956310825e-05),
               (1.29313391262165e-06, 6.46566956310825e-05)]
    # _ref_point = [(x[0] + x[1]) / 2 for x in _bounds[:5]]
    # manual tuned points 
    # _ref_point = [0.00012, 5e-06, 15e-06, 2.2e-06, 2.2e-06, 8.8e-06] 
    _ref_point = [1.4727e+03,  1.6391e+03, -1.9622e-04]
    
    def evaluate_true(self, X: Tensor) -> Tensor:
        nr = X.shape[-1] - 4
        Ell = 400
        Prated = 65000
        Vdc = 800
        Rlk = 0.005 * torch.ones(*X.shape[:-1], nr, device=X.device, dtype=X.dtype)
        omegasw = 32000 * math.pi

        L1 = X[...,0]
        L2 = X[...,1]
        L3 = X[...,2]
        Ck = X[...,3:-1]
        Cf = X[...,-1]
        
        ck_range = torch.arange(1, nr + 1, device=X.device, dtype=X.dtype)
        for _ in X.shape[:-1]:
            ck_range = ck_range.unsqueeze(0)
        ck_range = ck_range.repeat(*X.shape[:-1], 1)
        
        Lk = (Ck * (ck_range * omegasw)**2).reciprocal()
            
        def glc(s):
            num = L2 * s * (L3 * Cf * s**2 + 1) + L3 * s
            denom = Lk * s.unsqueeze(-1) + Rlk + 1./ (Ck * s.unsqueeze(-1))
            return (num.unsqueeze(-1) / denom).sum(-1)
        
        def gfun(s):
            f1 = L1 * s * glc(s)
            f2 = L2 * s * (L3 * Cf * s**2 + 1)
            f3 = L3 * s
            return 1./(f1 + f2 + f3)
        
        def fi(i):
            one_i = torch.ones(*X.shape[:-1], 2, device=X.device, dtype=X.dtype)
            one_i[...,0] = 0.
            sval = torch.view_as_complex(i * omegasw * one_i)
            gres = gfun(i * omegasw * sval)
            return 20 * torch.log(gres.real**2 + gres.imag**2)
                        
        res1 = [fi(i) for i in range(1, nr+1)]     
        print(len(res1))
        res2 = (L1 + L2 + L3).squeeze(-1) + Lk.sum(-1)
        # return res2
        
        if X.ndim == 2:
            return torch.stack((*res1, res2)).t()
          
        return torch.cat((*res1, res2), dim=-1)
    
    def evaluate_slack_true(self, X: Tensor) -> Tensor:
        nr = 4
        Vdc = 800
        omega0 = 100 * math.pi
        omegasw = 32000 * math.pi
        Iref = 141
        Rlk = 0.005 * torch.ones(*X.shape[:-1], nr, device=X.device, dtype=X.dtype)
        Ell = 400
        Prated = 65000
        Rb = Ell**2/Prated
        
        L1 = X[...,0]
        L2 = X[...,1]
        L3 = X[...,2]
        Ck = X[...,3:-1]
        Cf = X[...,-1]
          
        g1 = Ck.sum(-1) + Cf - 0.05 / (Rb * omega0)
        g2 = L1 + L2 + L3 - 0.1 * Rb / omega0
#         g31 = 0.2 - 2 * math.pi * Vdc / (8 * L1 * omegasw * Iref)
#         g32 = 2 * math.pi* Vdc / (8 * L1 * omegasw * Iref) - 0.4
        g4 = L2 + L3 - L1
        root_term = (L1 + L2 + L3) / (L1 * (L2 + L3) * (Ck.sum(-1) + Cf))
        root = root_term.sqrt()
        g51 = omegasw/2 - root
        g52 = root - 3*omegasw / 4   
        
        if X.ndim == 2:
            return -torch.stack((g2, g4)).t()
        
        return -torch.cat((g2, g4),dim=-1)                         
    