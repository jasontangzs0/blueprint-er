"""Run LLM-CER in independent processes over disjoint block shards (their ThreadPoolExecutor path deadlocks
on this machine). Same pipeline as scripts/run_pipeline.py: embeddings -> LSH blocks -> per-block
NRS / in-context clustering (+MDG) / CMR, sequential within a process.
  prep : embeddings, similarity matrix, blocks -> cache/<name>/
  run  : --shard i --nshards n : process blocks[i::n] -> cache/<name>/shard_i.json (clusters, stats)
  merge: -> final_results_<name>.txt + stats_<name>.json
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["prep", "run", "merge"]); ap.add_argument("--name", required=True)
ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1)
ap.add_argument("--block-threshold", type=float, default=0.0, help="fixed LSH block threshold (0 = dynamic mu+2.5sd)"); ap.add_argument("--reuse", default="", help="cache name whose vectors/simi to reuse")
a = ap.parse_args()
C = f"cache/{a.name}"; os.makedirs(C, exist_ok=True)
from llmcer.config import DATASET_PATH, SET_SIZE, SET_DIVERSITY
if a.mode == "prep":
    from llmcer.vectorization import cal_total_simi_vector
    from llmcer.clustering import lsh_block
    t0 = time.time()
    if a.reuse:
        data = pd.read_csv(DATASET_PATH, encoding="utf-8"); vectors = list(np.load(f"cache/{a.reuse}/vectors.npy")); simi = np.load(f"cache/{a.reuse}/simi.npy")
    else:
        vectors, simi, data = cal_total_simi_vector(DATASET_PATH)
    mu, sd = float(np.mean(simi)), float(np.std(simi)); bt = a.block_threshold or min(mu + 2.5 * sd, 0.99); mt = min(mu + 3.0 * sd, 0.90)
    blocks = lsh_block(vectors, data, bt)
    np.save(f"{C}/vectors.npy", np.array(vectors)); np.save(f"{C}/simi.npy", simi.astype(np.float32))
    json.dump({"blocks": [list(map(int, b)) for b in blocks], "block_threshold": bt, "merge_threshold": mt, "mu": mu, "sd": sd}, open(f"{C}/blocks.json", "w"))
    print(f"prep: {len(data)} records, block threshold {bt:.3f} (mu {mu:.3f} sd {sd:.3f}), {len(blocks)} blocks, sizes max {max(len(b) for b in blocks)}, {time.time()-t0:.0f}s", flush=True)
elif a.mode == "run":
    from llmcer.pipeline import run_blocks
    data = pd.read_csv(DATASET_PATH, encoding="utf-8")
    vectors = np.load(f"{C}/vectors.npy"); simi = np.load(f"{C}/simi.npy", mmap_mode="r"); B = json.load(open(f"{C}/blocks.json"))["blocks"]   # mmap: shards share one copy
    mine = sorted(B, key=len, reverse=True)[a.shard::a.nshards]; t0 = time.time()   # largest blocks spread across shards
    print(f"shard {a.shard}/{a.nshards}: {len(mine)} blocks", flush=True)
    clusters, stats = run_blocks(list(vectors), simi, mine, data, S_s=SET_SIZE, S_d=SET_DIVERSITY, parallel=False)
    stats["wall"] = time.time() - t0
    json.dump({"clusters": [list(map(int, c)) for c in clusters], "stats": stats}, open(f"{C}/shard_{a.shard}.json", "w"))
    print(f"shard {a.shard} done: {len(clusters)} clusters, {stats}", flush=True)
else:
    clusters, tot = [], {}
    for f in sorted(os.listdir(C)):
        if f.startswith("shard_"):
            d = json.load(open(f"{C}/{f}")); clusters += d["clusters"]
            for k, v in d["stats"].items(): tot[k] = tot.get(k, 0) + v
    with open(f"final_results_{a.name}.txt", "w") as f:
        for c in clusters: f.write(" ".join(map(str, c)) + "\n")
    json.dump(tot, open(f"stats_{a.name}.json", "w"), indent=1)
    print(f"merged {len(clusters)} clusters from {sum(1 for f in os.listdir(C) if f.startswith('shard_'))} shards; totals {tot}")
