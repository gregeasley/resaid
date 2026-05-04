#!/usr/bin/env python3
"""
Test script for decline_solver class to ensure functionality is preserved after cleanup.
"""

import sys
import os
import pandas as pd
import numpy as np
import time

# Add the parent directory to the path to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resaid.dca import decline_solver, decline_curve

def test_decline_solver_basic():
    """Test basic decline solver functionality"""
    print("Testing basic decline solver functionality...")
    
    # Test case 1: Solve for qi and t_max
    solver1 = decline_solver(
        qf=1000,
        de=0.1/12,  # 10% annual decline
        eur=50000,
        b=1.0,
        dmin=0.01/12
    )
    
    qi1, t_max1, qf1, de1, eur1, warning1, delta1 = solver1.solve()
    
    print(f"Test 1 - Solve for qi and t_max:")
    print(f"  qi: {qi1:.2f}")
    print(f"  t_max: {t_max1}")
    print(f"  qf: {qf1:.2f}")
    print(f"  de: {de1:.6f}")
    print(f"  eur: {eur1:.2f}")
    print(f"  warning: {warning1}")
    print(f"  delta: {delta1:.2f}")
    
    # Verify reasonable results
    assert qi1 > 0, "Initial rate should be positive"
    assert t_max1 > 0, "Time max should be positive"
    assert abs(qf1 - 1000) < 1e-6, "Final rate should match input"
    assert abs(de1 - 0.1/12) < 1e-6, "Decline rate should match input"
    assert abs(eur1 - 50000) < 1e-6, "EUR should match input"
    
    return True

def test_decline_solver_qi_qf():
    """Test solving for qi and qf"""
    print("\nTesting decline solver with qi and qf missing...")
    
    solver2 = decline_solver(
        de=0.15/12,  # 15% annual decline
        eur=75000,
        b=0.8,
        dmin=0.01/12
    )
    
    qi2, t_max2, qf2, de2, eur2, warning2, delta2 = solver2.solve()
    
    print(f"Test 2 - Solve for qi and qf:")
    print(f"  qi: {qi2:.2f}")
    print(f"  t_max: {t_max2}")
    print(f"  qf: {qf2:.2f}")
    print(f"  de: {de2:.6f}")
    print(f"  eur: {eur2:.2f}")
    print(f"  warning: {warning2}")
    print(f"  delta: {delta2:.2f}")
    
    # Verify reasonable results
    assert qi2 > 0, "Initial rate should be positive"
    assert qf2 > 0, "Final rate should be positive"
    assert abs(de2 - 0.15/12) < 1e-6, "Decline rate should match input"
    assert abs(eur2 - 75000) < 1e-6, "EUR should match input"
    
    return True

def test_decline_solver_qi_de():
    """Test solving for qi and de"""
    print("\nTesting decline solver with qi and de missing...")
    
    solver3 = decline_solver(
        qf=500,
        eur=30000,
        b=1.2,
        dmin=0.01/12
    )
    
    qi3, t_max3, qf3, de3, eur3, warning3, delta3 = solver3.solve()
    
    print(f"Test 3 - Solve for qi and de:")
    print(f"  qi: {qi3:.2f}")
    print(f"  t_max: {t_max3}")
    print(f"  qf: {qf3:.2f}")
    print(f"  de: {de3:.6f}")
    print(f"  eur: {eur3:.2f}")
    print(f"  warning: {warning3}")
    print(f"  delta: {delta3:.2f}")
    
    # Verify reasonable results
    assert qi3 > 0, "Initial rate should be positive"
    assert de3 > 0, "Decline rate should be positive"
    assert abs(qf3 - 500) < 1e-6, "Final rate should match input"
    assert abs(eur3 - 30000) < 1e-6, "EUR should match input"
    
    return True

def test_decline_solver_qi_eur():
    """Test solving for qi and eur"""
    print("\nTesting decline solver with qi and eur missing...")
    
    solver4 = decline_solver(
        qf=2000,
        de=0.2/12,  # 20% annual decline
        b=0.9,
        dmin=0.01/12
    )
    
    qi4, t_max4, qf4, de4, eur4, warning4, delta4 = solver4.solve()
    
    print(f"Test 4 - Solve for qi and eur:")
    print(f"  qi: {qi4:.2f}")
    print(f"  t_max: {t_max4}")
    print(f"  qf: {qf4:.2f}")
    print(f"  de: {de4:.6f}")
    print(f"  eur: {eur4:.2f}")
    print(f"  warning: {warning4}")
    print(f"  delta: {delta4:.2f}")
    
    # Verify reasonable results
    assert qi4 > 0, "Initial rate should be positive"
    assert eur4 > 0, "EUR should be positive"
    assert abs(qf4 - 2000) < 1e-6, "Final rate should match input"
    assert abs(de4 - 0.2/12) < 1e-6, "Decline rate should match input"
    
    return True

def test_decline_solver_all_parameters():
    """Test decline solver with all parameters provided"""
    print("\nTesting decline solver with all parameters provided...")
    
    solver5 = decline_solver(
        qi=5000,
        qf=100,
        de=0.12/12,  # 12% annual decline
        eur=100000,
        b=1.1,
        dmin=0.01/12,
        t_max=600
    )
    
    qi5, t_max5, qf5, de5, eur5, warning5, delta5 = solver5.solve()
    
    print(f"Test 5 - All parameters provided:")
    print(f"  qi: {qi5:.2f}")
    print(f"  t_max: {t_max5}")
    print(f"  qf: {qf5:.2f}")
    print(f"  de: {de5:.6f}")
    print(f"  eur: {eur5:.2f}")
    print(f"  warning: {warning5}")
    print(f"  delta: {delta5:.2f}")
    
    # Verify all parameters match input
    assert abs(qi5 - 5000) < 1e-6, "Initial rate should match input"
    assert abs(qf5 - 100) < 1e-6, "Final rate should match input"
    assert abs(de5 - 0.12/12) < 1e-6, "Decline rate should match input"
    assert abs(eur5 - 100000) < 1e-6, "EUR should match input"
    assert abs(t_max5 - 600) < 1e-6, "Time max should match input"
    assert warning5 == False, "No warning should be raised when all parameters provided"
    
    return True

def test_decline_solver_edge_cases():
    """Test decline solver with edge cases"""
    print("\nTesting decline solver edge cases...")
    
    # Test with very small EUR
    solver6 = decline_solver(
        qf=100,
        de=0.1/12,
        eur=1000,
        b=1.0,
        dmin=0.01/12
    )
    
    qi6, t_max6, qf6, de6, eur6, warning6, delta6 = solver6.solve()
    
    print(f"Test 6 - Small EUR:")
    print(f"  qi: {qi6:.2f}")
    print(f"  t_max: {t_max6}")
    print(f"  qf: {qf6:.2f}")
    print(f"  de: {de6:.6f}")
    print(f"  eur: {eur6:.2f}")
    print(f"  warning: {warning6}")
    print(f"  delta: {delta6:.2f}")
    
    # Test with very large EUR
    solver7 = decline_solver(
        qf=5000,
        de=0.05/12,
        eur=1000000,
        b=0.8,
        dmin=0.01/12
    )
    
    qi7, t_max7, qf7, de7, eur7, warning7, delta7 = solver7.solve()
    
    print(f"Test 7 - Large EUR:")
    print(f"  qi: {qi7:.2f}")
    print(f"  t_max: {t_max7}")
    print(f"  qf: {qf7:.2f}")
    print(f"  de: {de7:.6f}")
    print(f"  eur: {eur7:.2f}")
    print(f"  warning: {warning7}")
    print(f"  delta: {delta7:.2f}")
    
    # Verify reasonable results for edge cases
    assert qi6 > 0 and qi7 > 0, "Initial rates should be positive"
    assert t_max6 > 0 and t_max7 > 0, "Time max should be positive"
    
    return True

def test_decline_solver_consistency():
    """Test that decline solver produces consistent results"""
    print("\nTesting decline solver consistency...")
    
    # Run the same solver multiple times
    solver = decline_solver(
        qf=1500,
        de=0.08/12,
        eur=50000,
        b=1.0,
        dmin=0.01/12
    )
    
    results = []
    for i in range(5):
        qi, t_max, qf, de, eur, warning, delta = solver.solve()
        results.append((qi, t_max, qf, de, eur, warning, delta))
    
    # Check that all results are identical
    for i in range(1, len(results)):
        assert abs(results[i][0] - results[0][0]) < 1e-10, f"qi should be consistent, got {results[i][0]} vs {results[0][0]}"
        assert abs(results[i][1] - results[0][1]) < 1e-10, f"t_max should be consistent, got {results[i][1]} vs {results[0][1]}"
        assert abs(results[i][2] - results[0][2]) < 1e-10, f"qf should be consistent, got {results[i][2]} vs {results[0][2]}"
        assert abs(results[i][3] - results[0][3]) < 1e-10, f"de should be consistent, got {results[i][3]} vs {results[0][3]}"
        assert abs(results[i][4] - results[0][4]) < 1e-10, f"eur should be consistent, got {results[i][4]} vs {results[0][4]}"
    
    print("✓ All results are consistent across multiple runs")
    
    return True

def test_dca_delta_function():
    """Test the dca_delta function directly"""
    print("\nTesting dca_delta function...")
    
    solver = decline_solver(
        qi=3000,
        qf=100,
        de=0.1/12,
        eur=50000,
        b=1.0,
        dmin=0.01/12,
        t_max=1200
    )
    
    # Test with current parameters
    delta1 = solver.dca_delta([solver.qi, solver.de])
    print(f"Delta with current parameters: {delta1:.2f}")
    
    # Test with modified parameters
    delta2 = solver.dca_delta([solver.qi * 1.1, solver.de * 1.1])
    print(f"Delta with modified parameters: {delta2:.2f}")
    
    # Delta should be a reasonable value
    assert delta1 >= 0, "Delta should be non-negative"
    assert delta2 >= 0, "Delta should be non-negative"
    
    return True

def main():
    """Run all decline solver tests"""
    print("=== Decline Solver Test Suite ===")
    print("Testing decline_solver class functionality after cleanup...")
    
    tests = [
        test_decline_solver_basic,
        test_decline_solver_qi_qf,
        test_decline_solver_qi_de,
        test_decline_solver_qi_eur,
        test_decline_solver_all_parameters,
        test_decline_solver_edge_cases,
        test_decline_solver_consistency,
        test_dca_delta_function
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
                print(f"✓ {test.__name__} passed")
            else:
                print(f"✗ {test.__name__} failed")
        except Exception as e:
            print(f"✗ {test.__name__} failed with exception: {e}")
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {passed}/{total}")
    print(f"Success rate: {passed/total:.1%}")
    
    if passed == total:
        print("✓ All decline solver tests passed!")
        return True
    else:
        print("✗ Some decline solver tests failed!")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
