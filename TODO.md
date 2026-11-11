<!-- SPDX-License-Identifier: Apache-2.0 -->

# Grider TODO

最終更新: 2026-11-10

## 完了

- [x] Attention基本カーネルのPython試作・検証
  - `grider/kernels.py`にscaled dot-product attention、stable softmax、causal maskを実装。
  - `grider/examples/attention.py`と単体テストで実行確認。これはPython参照実装で、命令列へのコンパイルは未対応。
- [x] ISAの確定（v0、Reduction追加時にv0.1へ拡張）
  - opcode、型タグ、予約値、型継承、丸め、近傍方向、ホスト発行規約を`docs/isa.md`に定義。
- [x] SystemVerilogのセル・タイル機能実装
  - `rtl/grider_tile.sv`に256セルのSIMDタイル、型付きレジスタ/SRAM、ALU/MAC、BF16、近傍ポートを実装。
  - `rtl/grider_mesh.sv`に命令ブロードキャストとタイル間halo接続を実装。Icarus Verilogで機能シミュレーション済み。
- [x] BF16/INT8演算の実装
  - PythonとRTLに整数演算およびBF16 add/sub/mul/MAC/min/maxを実装。
  - `grider.verify_rtl`で27命令を実行し、256セルの全レジスタ/SRAM計8,192ワードを比較。一致を確認。
- [x] マルチタイル化（機能プロトタイプ）
  - Python MeshとRTL Meshを実装。2×2構成で8方向haloを比較し、9,216レジスタワードが一致。
- [x] ISA v0.3セル・データフロー拡張（AI/描画GPU）
  - `TRANSPOSE`、`REDUCE_SUM_COL`/`REDUCE_MAX_COL`、`SCAN_SUM`、`DOT_ROW`、`GATHER`/`SCATTER`、`ROW/COL_BROADCAST`、整数`DIV`、F32 elementwiseを追加。Python/RTLの全レジスタ/SRAM一致を`verify_rtl`で確認。
  - `grider.kernels`にRMSNorm/SiLU/SwiGLU/RoPE/conv2d/histogram/top-k、`grider.render`にblur/Sobel/bilinear/blend/barycentric/Lambertを追加。`grider.dataflow`にAI/描画パイプライン見積を追加。`lowering`にtranspose/QK loweringを追加。
- [x] v0.3のPPA評価と検証フォローアップ
  - Sky130HD標準セルパスで1 PEを合成/STA。面積1,271,974.92 µm²、Fmax 0.461 MHz（v0.2比で面積+63%、大幅なタイミング悪化）。`docs/synthesis.md`に記録。
  - PythonのF32演算をビット正確なIEEE-754参照モデルに置き換え、Python/RTL全8,192ワード一致を確認。
  - `Makefile`の`examples`にv0.3のexamplesを追加し、CIで実行。
  - `DOT_ROW`の整数乗算を64bitに制限（I64以下の型に対して128bit乗算は不要）。

## 進行中

- [ ] 近傍通信・Reductionの最適化（機能実装は完了、物理最適化は継続）
  - [x] 8方向の同一タイル内・タイル間近傍通信を実装し、2×2メッシュで照合。
  - [x] `REDUCE_SUM` / `REDUCE_MAX`を追加。マスク付き16セル行Reductionを4段balanced treeで実装し、Python/RTLを照合。
  - [ ] FPGA上の配線遅延、帯域、面積を測り、物理制約に合わせた最適化を行う。
- [ ] マルチタイル化・耐故障設計
  - [x] マルチタイル機能プロトタイプは完了。
  - [ ] 故障検出、迂回、タイル隔離、縮退動作は未設計。
- [ ] v0.3のクリティカルパス改善
  - [x] 1 PE合成でcritical pathが約5,000段、maj3（加算器）支配であることを特定。
  - [x] `SCAN_SUM`をKogge-Stone並列prefix scanへ、`DOT_ROW`を平衡ツリーへ置換。
  - [x] SRAM22マクロパスのv0.3評価を実施。
  - [x] ボトルネックを特定: main `always_comb` の per-lane 型/opcode選択（pre-mapのmuxが13,884個、v0.2の4,518個の約3倍）。
  - [x] ABCの`dch`が合成のボトルネック（3,171秒）だったことを特定。`-script "+strash; dch -f; map"`に変更し、ABC 259秒・Fmax 0.452→1.290 MHz。
  - [x] 1 PEフロー（LANES=1）はタイル横断命令のデータパスを最適化で落とすことを発見（`$mul`が11個のみ）。v0.3のPPA数値はper-laneのみ。
  - [x] 浮動小数点の正規化を逐次シフトループからclz＋バレルシフトへ置換（stickyビットもマスク化）。最長経路1,807→293段（6.2倍）、演算結果はビット一致のまま。
  - [ ] 残存ボトルネックは128bit幅のopcode/型選択ネット（selectのfanout 50〜200）。演算と結果選択の間にper-laneのパイプラインレジスタが必要で、フルタイルでは256×132bit分のflip-flop追加となる（1 PEフローでは測定不可）。
  - [ ] タイル横断命令を消さない合成フローを用意し、v0.3全体のPPAを再測定する。

## 未着手 / 外部条件待ち

- [ ] FPGAで動作・リソース使用量を検証
  - 対象FPGAの型番、ボード、合成/配置配線ツールが必要。Icarusの機能シミュレーションはFPGA動作検証の代替ではない。
- [ ] シストリックアレイとの性能比較
  - 比較対象、データ型、カーネル、クロック/面積/電力の評価条件を設定していない。
- [ ] ASIC化・ウェハースケール化の検討
  - 面積/電力/配線/製造歩留まりを含む設計探索は未実施。

## 次の実装項目

対象FPGAが決まるままでも、v0.3の`DOT_ROW`クリティカルパス対策（パイプライン化/ツリー化）とSRAM22パス評価を進める。

