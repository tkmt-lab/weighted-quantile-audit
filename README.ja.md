# 重み付き分位点の監査

版 0.1.0 · 公開前の草案 · DOI 未付与

重みの単位を変えただけで分位点が変わったとき、小さな標本について statsmodels の `DescrStatsW.quantile` の返値を調べる道具です。入力した有理数、ライブラリに渡った浮動小数点数、それぞれの厳密な分位点を JSON に保存し、同じファイルを別の人が検算できます。[English](README.md)

## 2 点の例を試す

同梱の観測を再生する環境は Linux と CPython 3.12.14 です。この README があるディレクトリで実行します。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -B audit.py examples/two_point_tiny.json > witness.json
python3 -B checker.py witness.json
.venv/bin/python -B replay.py witness.json
```

値は 0 と 2、重みはどちらも 2⁻³⁵、求めるのは下側 ¼ の分位点です。最初の点だけで全質量の半分に達するので、厳密な答えは 0 です。statsmodels 0.15.0 は 1 を返します。出力の `implementation_diagnosis` は `TOLERANCE_ONLY_WITNESS` で、4 通りの有理数の証人はいずれも 0 を示します。`checker.py` は `"valid": true` を出力し、`replay.py` はライブラリを呼び直します。

[保存した 2 点の証人](evidence/two_point_tiny.json)の検算だけなら、Python 標準ライブラリで実行できます。

```sh
python3 -B checker.py evidence/two_point_tiny.json
```

## 既知の振る舞いと回避策

statsmodels は目標の質量と選ばれた累積重みの差が固定の絶対許容幅 `1e-10` 未満なら、次の点との平均を取ることがあります。上の例の差は 2⁻³⁶ なので 0 と 2 の平均になります。ここでは目標、累積重み、差はすべて二進浮動小数点で厳密に表せます。[statsmodels の実装](https://github.com/statsmodels/statsmodels/blob/v0.15.0/statsmodels/stats/weightstats.py)

この場合、分位点を計算する前に正の重みを合計 1 に正規化すると回避できます。

```python
import numpy as np
from statsmodels.stats.weightstats import DescrStatsW

x = [0., 2.]
w = np.array([2.**-35, 2.**-35])
print(DescrStatsW(x, weights=w).quantile([0.25], return_pandas=False))           # [1.]
print(DescrStatsW(x, weights=w / w.sum()).quantile([0.25], return_pandas=False)) # [0.]
```

[正規化前](examples/two_point_tiny.json)も[正規化後](examples/two_point_normalized.json)も厳密値は 0 です。人工的な重点サンプリングの例では、正規化すると返値が 14 から厳密値の 8 に戻ります。一方、合計 1 でも境界に十分近い確率には許容幅が効きます。等しい正規化済み重みで確率を ½ − 2⁻³⁵ にすると、隣り合う点の平均を返します。[重点サンプリングの重み](examples/importance_tiny.json)・[正規化後](examples/importance_normalized.json)

## 自分の入力を調べる

`audit.py` にファイルを渡すか、標準入力に次の形の JSON を渡します。

```json
{"x":[0,2],"w":["1/2","1/2"],"p":"0.25"}
```

キーは `x`（値）、`w`（正の重み）、`p`（0 と 1 の間の確率）の三つです。整数は JSON の数でも渡せます。小数や分数は文字列にすると、元の値と binary64 に変換した値を照合できます。標本は 1〜16 点で、入力は最大 64 KiB です。数の文字列は最大 96 文字、既約分数の分子・分母は各 128 ビットまで、小数の指数は −128〜128 です。変換後も重みは正、確率は端点の内側にある必要があります。

| `axes` の欄 | 真になる条件 |
|---|---|
| `definition_difference` | binary64 入力で境界平均と逆累積分布の厳密値が違う。内部境界では前者は隣接 2 点を平均し、後者は下側の点を選ぶ。 |
| `input_rounding_changes_value` | binary64 への入力変換で境界平均の厳密値が変わる。 |
| `implementation_value_mismatch` | binary64 入力での厳密な境界平均を浮動小数点に丸めた値と、実装の返値が違う。 |

複数の欄が同時に真になり得ます。証人には累積重みの上下限、目標、該当する点、厳密値が入ります。別プロセスの checker は Python 標準ライブラリで不等式と計算式を検算します。replay は実測値、Python のパッチ版、依存の版、ソースのハッシュも照合します。[出力の仕様](SCHEMA.md)・[計算式](MATHEMATICS.md)

## 固定版で再生する

```sh
bash reproduce.sh --install
```

依存の固定版を導入し、試験と保存した 102 観測（408 証人）の再生を行います。導入後は `bash reproduce.sh` でオフラインで繰り返せます。新しい入力の監査には Python 3.12 と固定版の数値ライブラリを使います。保存済み観測の再生には記録された Python のパッチ版まで一致する必要があります。[依存の固定版](requirements.lock)・[実行環境の照合項目](runtime-lock.json)

## 適用範囲と謝辞

対象は一次元の小標本と上の二つの定義です。失敗例の探索・縮小には別途 Hypothesis を使えます。複数の枝が同じ浮動小数点数を返す場合は `BRANCH_UNKNOWN` と表示します。診断で再構成した演算から実行枝を特定できる範囲には限りがあります。試験で確かめた入力は有限です。終了値 0 は監査完了（差を検出した場合を含む）、2 は入力の構文または範囲の問題、3 は環境不一致、4 は内部エラーまたは再検査失敗です。

境界平均の定義は statsmodels の開発者による文書に従いました。NumPy の逆累積分布、Jeremy Singer-Vine 氏らの weightedcalcs、Hypothesis の性質試験と縮小を比較に使いました。[statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.DescrStatsW.quantile.html)・[NumPy](https://numpy.org/doc/stable/reference/generated/numpy.percentile.html)・[weightedcalcs](https://pypi.org/project/weightedcalcs/)・[Hypothesis](https://hypothesis.readthedocs.io/)

## AI の利用と責任

OpenAI Codex を監査 CLI と checker の実装、比較と試験の実行、説明文の作成に使いました。例は計算で照合しました。人間による査読は受けていません。著者の滝本竜彦がコード、データ、結論に責任を負います。[引用情報](CITATION.cff)・[ライセンス](LICENSE)
