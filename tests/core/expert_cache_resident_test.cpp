// The Monitor's "experts cached" used to report `slots()` - the arena's capacity - rather than `resident()`,
// the slots actually holding an expert (the cache does not evict, so a run that routes fewer distinct experts
// than there are slots leaves the rest empty).  This pins the difference the engine now reports as
// `expert_slots_resident`.  Needs a CUDA device (exits 77 without one).
#include "strata/core/expert_cache.hpp"

#include <cuda_runtime.h>

#include <cstdio>
#include <string>

static int fail(const char* what, long long got, long long want) {
    std::fprintf(stderr, "%s: got %lld, want %lld\n", what, got, want);
    return 1;
}

int main() {
    int n = 0;
    if (cudaGetDeviceCount(&n) != cudaSuccess || n == 0) {
        std::puts("no CUDA device: skipped");
        return 77;
    }
    std::string err;

    {   // the global cursor (default) admission: one counter shared by every layer
        strata::core::ExpertCache cache;
        if (!cache.open(6, 3, 4, 1024, err)) {
            std::fprintf(stderr, "open: %s\n", err.c_str());
            return 1;
        }
        // freshly opened: capacity 6, nothing resident - where the Monitor's number was most inflated
        if (cache.slots() != 6) return fail("fresh slots", cache.slots(), 6);
        if (cache.resident() != 0) return fail("fresh resident", cache.resident(), 0);
        // five distinct (layer, expert) pairs: resident counts them, the capacity does not move
        const int64_t pairs[5][2] = {{0, 0}, {0, 1}, {1, 0}, {1, 2}, {2, 3}};
        for (int i = 0; i < 5; ++i)
            if (cache.admit(pairs[i][0], pairs[i][1]) < 0) return fail("admit", -1, i);
        if (cache.resident() != 5) return fail("resident after 5 admits", cache.resident(), 5);
        if (cache.slots() != 6) return fail("slots after 5 admits", cache.slots(), 6);
        // re-admitting a resident pair returns its slot and counts nothing again
        const int32_t s0 = cache.slot_of(0, 0);
        if (cache.admit(0, 0) != s0) return fail("re-admit slot", cache.admit(0, 0), s0);
        if (cache.resident() != 5) return fail("resident after re-admit", cache.resident(), 5);
        // the sixth distinct pair fills the arena; the seventh is refused (no eviction, deliberately)
        if (cache.admit(2, 0) != 5) return fail("sixth admit slot", cache.slot_of(2, 0), 5);
        if (cache.resident() != 6) return fail("resident when full", cache.resident(), 6);
        if (cache.admit(2, 1) != strata::core::kNotResident) return fail("seventh admit", 0, -1);
        if (cache.resident() != 6) return fail("resident after refusal", cache.resident(), 6);
    }

    {   // per-layer admission (R4.2g): each layer its own range, resident() the total admitted
        strata::core::ExpertCache cache;
        if (!cache.open(6, 3, 4, 1024, err)) {
            std::fprintf(stderr, "open: %s\n", err.c_str());
            return 1;
        }
        cache.set_per_layer_admission(true);
        if (cache.resident() != 0) return fail("fresh per-layer resident", cache.resident(), 0);
        if (cache.admit(0, 0) < 0 || cache.admit(0, 1) < 0 || cache.admit(2, 1) < 0)
            return fail("per-layer admit", -1, 0);
        if (cache.resident() != 3) return fail("per-layer resident", cache.resident(), 3);
        if (cache.slots() != 6) return fail("per-layer slots", cache.slots(), 6);
        if (cache.admit(0, 0) != cache.slot_of(0, 0)) return fail("per-layer re-admit", -1, 0);
        if (cache.resident() != 3) return fail("per-layer resident after re-admit", cache.resident(), 3);
    }

    std::puts("expert cache resident-vs-capacity: global and per-layer modes passed");
    return 0;
}
