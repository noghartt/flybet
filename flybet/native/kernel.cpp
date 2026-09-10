// Flybet's full-graph LIF integrator. Fixed 0.1 ms steps; no activity pruning.
// All physiology is an explicit approximation, not inferred from connectivity.
#include <cmath>
#include <cstdint>

extern "C" void fb_advance(
    int n, const int64_t* ptr, const int32_t* post, const float* weight,
    const float* rest, const uint8_t* kc, const uint8_t* mod_kind,
    float* v, float* g, float* adaptation, int32_t* refractory,
    int32_t* queue, int32_t* queue_count, int64_t* clock,
    float* pam, float* ppl, const float* drive, const float* params, int steps, int32_t* counts) {
    constexpr int delay = 18, slots = 19, refractory_steps = 22;
    const float tm = params[0], ts = params[1], ta = params[4];
    const float em = std::exp(-0.1f / tm), es = std::exp(-0.1f / ts);
    const float ea = std::exp(-0.1f / ta), ed = std::exp(-0.1f / params[5]);
    const float syn_factor = ts / (tm - ts), adaptation_factor = ta / (ta - tm);
    for (int t = 0; t < steps; ++t, ++(*clock)) {
        const int slot = *clock % slots;
        // An emitted spike reaches every retained target after 1.8 ms.
        for (int q = 0; q < queue_count[slot]; ++q) {
            const int i = queue[slot * n + q];
            for (int64_t e = ptr[i]; e < ptr[i + 1]; ++e) {
                const int j = post[e];
                if (mod_kind[i] == 1) pam[j] += std::abs(weight[e]) / .275f;
                else if (mod_kind[i] == 2) ppl[j] += std::abs(weight[e]) / .275f;
                else if (mod_kind[i] == 0 && refractory[j] == 0) g[j] += weight[e];
                // Other pure modulators retain edges but have no modeled effect.
            }
        }
        queue_count[slot] = 0;
        const int future = (*clock + delay) % slots;
        for (int i = 0; i < n; ++i) {
            pam[i] *= ed;
            ppl[i] *= ed;
            if (refractory[i] > 0) {
                --refractory[i];
                v[i] = rest[i];
            } else {
                v[i] = rest[i] + (v[i] - rest[i]) * em + drive[i] * (1.f - em)
                    + g[i] * (em - es) * syn_factor
                    - adaptation[i] * adaptation_factor * (ea - em);
            }
            g[i] *= es;
            adaptation[i] *= ea;
            if (refractory[i] == 0 && v[i] > params[2]) {
                ++counts[i];
                queue[future * n + queue_count[future]++] = i;
                v[i] = rest[i];
                g[i] = 0.f;
                refractory[i] = refractory_steps;
                if (kc[i]) adaptation[i] += params[3];
            }
        }
    }
}
