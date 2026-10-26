# Grider TODO

最終更新: 2026-10-26

## 完了

- [x] Attention基本カーネルのPython試作・検証
  - `grider/kernels.py`にscaled dot-product attention、stable softmax、causal maskを実装。
  - `grider/examples/attention.py`と単体テストで実行確認。これはPython参照実装で、命令列へのコンパイルは未対応。
- [x] ISA v0の確定
  - opcode、型タグ、予約値、型継承、丸め、近傍方向、ホスト発行規約を`docs/isa.md`に定義。
- [x] SystemVerilogのセル・タイル機能実装
  - `rtl/grider_tile.sv`に256セルのSIMDタイル、型付きレジスタ/SRAM、ALU/MAC、BF16、近傍ポートを実装。
  - `rtl/grider_mesh.sv`に命令ブロードキャストとタイル間halo接続を実装。Icarus Verilogで機能シミュレーション済み。
- [x] BF16/INT8演算の実装
  - PythonとRTLに整数演算およびBF16 add/sub/mul/MAC/min/maxを実装。
  - `grider.verify_rtl`で21命令を実行し、256セルの全レジスタ/SRAM計8,192ワードを比較。一致を確認。
- [x] マルチタイル化（機能プロトタイプ）
  - Python MeshとRTL Meshを実装。2×2構成で8方向haloを比較し、9,216レジスタワードが一致。

## 進行中

- [ ] 近傍通信・Reductionの最適化
  - [x] 8方向の同一タイル内・タイル間近傍通信を実装し、2×2メッシュで照合。
  - [ ] Reduction命令と木構造/帯域最適化は未実装。
- [ ] マルチタイル化・耐故障設計
  - [x] マルチタイル機能プロトタイプは完了。
  - [ ] 故障検出、迂回、タイル隔離、縮退動作は未設計。

## 未着手 / 外部条件待ち

- [ ] FPGAで動作・リソース使用量を検証
  - 対象FPGAの型番、ボード、合成/配置配線ツールが必要。Icarusの機能シミュレーションはFPGA動作検証の代替ではない。
- [ ] シストリックアレイとの性能比較
  - 比較対象、データ型、カーネル、クロック/面積/電力の評価条件を設定していない。
- [ ] ASIC化・ウェハースケール化の検討
  - 面積/電力/配線/製造歩留まりを含む設計探索は未実施。

## 次の実装項目

ReductionプリミティブをISA・Pythonモデル・RTL・等価比較に追加し、行方向のsum/maxから検証する。
