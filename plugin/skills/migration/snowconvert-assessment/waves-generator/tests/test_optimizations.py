#!/usr/bin/env python3
"""
Quick validation test for optimized analyze_dependencies.py

Tests that the iterative implementations work correctly and don't
hit stack overflow issues.
"""

import sys
from pathlib import Path

# Add scripts directory to path
scripts_path = Path(__file__).parent.parent / 'scripts'
sys.path.insert(0, str(scripts_path))

from analyze_dependencies import DependencyGraph


def test_iterative_scc():
    """Test that find_strongly_connected_components works iteratively."""
    print("Testing find_strongly_connected_components (Tarjan's algorithm)...")
    
    graph = DependencyGraph[str]()
    
    # Create a deep chain (would overflow with recursion)
    depth = 10_000
    for i in range(depth - 1):
        graph.add_edge(f"node_{i}", f"node_{i+1}")
    
    print(f"  Created chain of {depth:,} nodes")
    
    try:
        sccs = graph.find_strongly_connected_components()
        print(f"  ✓ Found {len(sccs):,} SCCs (no stack overflow!)")
        
        # Should be all single-node SCCs (no cycles in a chain)
        assert len(sccs) == depth, f"Expected {depth} SCCs, got {len(sccs)}"
        assert all(len(scc) == 1 for scc in sccs), "All SCCs should be single nodes"
        print(f"  ✓ All SCCs are single nodes (correct for chain graph)")
        
        return True
    except RecursionError:
        print(f"  ✗ FAILED: RecursionError (still using recursive implementation)")
        return False


def test_iterative_wcc():
    """Test that find_weakly_connected_components works iteratively."""
    print("\nTesting find_weakly_connected_components (iterative DFS)...")
    
    graph = DependencyGraph[str]()
    
    # Create a deep chain
    depth = 10_000
    for i in range(depth - 1):
        graph.add_edge(f"node_{i}", f"node_{i+1}")
    
    print(f"  Created chain of {depth:,} nodes")
    
    try:
        wccs = graph.find_weakly_connected_components()
        print(f"  ✓ Found {len(wccs):,} WCCs (no stack overflow!)")
        
        # Should be 1 WCC (entire chain is connected)
        assert len(wccs) == 1, f"Expected 1 WCC, got {len(wccs)}"
        assert len(wccs[0]) == depth, f"Expected WCC size {depth}, got {len(wccs[0])}"
        print(f"  ✓ Single WCC with {depth:,} nodes (correct for chain graph)")
        
        return True
    except RecursionError:
        print(f"  ✗ FAILED: RecursionError (still using recursive implementation)")
        return False


def test_scc_with_cycles():
    """Test SCC detection with actual cycles."""
    print("\nTesting SCC with cycles...")
    
    graph = DependencyGraph[str]()
    
    # Create 3 cycles
    # Cycle 1: A -> B -> C -> A
    graph.add_edge("A", "B")
    graph.add_edge("B", "C")
    graph.add_edge("C", "A")
    
    # Cycle 2: D -> E -> F -> D
    graph.add_edge("D", "E")
    graph.add_edge("E", "F")
    graph.add_edge("F", "D")
    
    # Cycle 3: G -> H -> G
    graph.add_edge("G", "H")
    graph.add_edge("H", "G")
    
    # Single node (no cycle)
    graph.all_nodes.add("Z")
    
    sccs = graph.find_strongly_connected_components()
    print(f"  Found {len(sccs)} SCCs")
    
    # Should find 4 SCCs: 3 cycles + 1 single node
    assert len(sccs) == 4, f"Expected 4 SCCs, got {len(sccs)}"
    
    # Check cycle sizes
    scc_sizes = sorted([len(scc) for scc in sccs], reverse=True)
    assert scc_sizes == [3, 3, 2, 1], f"Expected sizes [3, 3, 2, 1], got {scc_sizes}"
    print(f"  ✓ Correctly identified 3 cycles and 1 single node")
    
    # Find the actual cycles
    cycles = graph.find_cycles()
    assert len(cycles) == 3, f"Expected 3 cycles, got {len(cycles)}"
    print(f"  ✓ find_cycles() correctly identified 3 cycles")
    
    return True


def test_transitive_with_depth_limit():
    """Test transitive operations with depth limiting."""
    print("\nTesting transitive operations with depth limiting...")
    
    graph = DependencyGraph[str]()
    
    # Create chain: A -> B -> C -> D -> E -> F
    graph.add_edge("A", "B")
    graph.add_edge("B", "C")
    graph.add_edge("C", "D")
    graph.add_edge("D", "E")
    graph.add_edge("E", "F")
    
    # Test unlimited depth
    deps_unlimited = graph.get_transitive_dependencies("A")
    assert len(deps_unlimited) == 5, f"Expected 5 transitive deps, got {len(deps_unlimited)}"
    print(f"  ✓ Unlimited depth: {len(deps_unlimited)} dependencies")
    
    # Test depth limit = 2 (should get B, C only)
    deps_limited = graph.get_transitive_dependencies("A", max_depth=2)
    assert len(deps_limited) == 2, f"Expected 2 deps with depth=2, got {len(deps_limited)}"
    assert deps_limited == {"B", "C"}, f"Expected {{B, C}}, got {deps_limited}"
    print(f"  ✓ Depth limit = 2: {len(deps_limited)} dependencies {deps_limited}")
    
    # Test reverse direction
    dependents_unlimited = graph.get_transitive_dependents("F")
    assert len(dependents_unlimited) == 5, f"Expected 5 transitive dependents, got {len(dependents_unlimited)}"
    print(f"  ✓ Unlimited depth (reverse): {len(dependents_unlimited)} dependents")
    
    dependents_limited = graph.get_transitive_dependents("F", max_depth=2)
    assert len(dependents_limited) == 2, f"Expected 2 dependents with depth=2, got {len(dependents_limited)}"
    assert dependents_limited == {"E", "D"}, f"Expected {{E, D}}, got {dependents_limited}"
    print(f"  ✓ Depth limit = 2 (reverse): {len(dependents_limited)} dependents {dependents_limited}")
    
    return True


def test_performance_characteristics():
    """Test with realistic medium-scale graph."""
    print("\nTesting performance with 50K nodes...")
    
    graph = DependencyGraph[str]()
    
    # Create a hierarchical graph (tree)
    import time
    start = time.time()
    
    nodes = [f"node_{i}" for i in range(50_000)]
    for i, node in enumerate(nodes):
        graph.all_nodes.add(node)
    
    # Create hierarchical structure (each node has 5 children)
    for i in range(10_000):
        for j in range(5):
            child_idx = i * 5 + j + 1
            if child_idx < len(nodes):
                graph.add_edge(nodes[i], nodes[child_idx])
    
    build_time = time.time() - start
    print(f"  Graph built in {build_time:.2f}s")
    print(f"  Nodes: {len(graph.all_nodes):,}")
    print(f"  Edges: {sum(len(deps) for deps in graph.graph.values()):,}")
    
    # Test SCC
    start = time.time()
    sccs = graph.find_strongly_connected_components()
    scc_time = time.time() - start
    print(f"  ✓ SCC computation: {scc_time:.2f}s ({len(sccs):,} components)")
    
    # Test WCC
    start = time.time()
    wccs = graph.find_weakly_connected_components()
    wcc_time = time.time() - start
    print(f"  ✓ WCC computation: {wcc_time:.2f}s ({len(wccs):,} components)")
    
    # Test cycles
    start = time.time()
    cycles = graph.find_cycles()
    cycle_time = time.time() - start
    print(f"  ✓ Cycle detection: {cycle_time:.2f}s ({len(cycles):,} cycles)")
    
    total_time = build_time + scc_time + wcc_time + cycle_time
    print(f"  Total time: {total_time:.2f}s")
    
    # Performance check: should complete in reasonable time
    assert total_time < 120, f"Performance issue: took {total_time:.2f}s (expected < 120s)"
    print(f"  ✓ Performance acceptable")
    
    return True


def main():
    """Run all validation tests."""
    print("=" * 80)
    print("OPTIMIZED DEPENDENCY GRAPH VALIDATION TESTS")
    print("=" * 80)
    print()
    
    tests = [
        ("Iterative SCC", test_iterative_scc),
        ("Iterative WCC", test_iterative_wcc),
        ("SCC with Cycles", test_scc_with_cycles),
        ("Transitive with Depth Limit", test_transitive_with_depth_limit),
        ("Performance (50K nodes)", test_performance_characteristics),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"  ✗ FAILED with exception: {e}")
            results.append((name, False))
    
    print()
    print("=" * 80)
    print("TEST RESULTS")
    print("=" * 80)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(success for _, success in results)
    
    print()
    if all_passed:
        print("🎉 ALL TESTS PASSED - Optimizations working correctly!")
        return 0
    else:
        failed_count = sum(1 for _, success in results if not success)
        print(f"❌ {failed_count} TEST(S) FAILED - Review implementation")
        return 1


if __name__ == '__main__':
    sys.exit(main())
