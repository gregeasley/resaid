#!/usr/bin/env python3
"""Minimal ``decline_solver`` demo (dev / manual check). Run from repo root."""

from resaid.dca import decline_solver


def main():
    solver = decline_solver(
        qi=16805,
        qf=3000,
        eur=1_104_336.17516371,
        b=0.01,
        dmin=0.01 / 12,
    )
    print(solver.solve())


if __name__ == "__main__":
    main()
