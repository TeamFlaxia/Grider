.PHONY: test verify examples benchmark

test:
	python -m unittest discover -s tests -v

verify:
	python -m grider.verify_rtl
	python -m grider.verify_mesh_rtl

examples:
	python -m grider.examples.vector_add
	python -m grider.examples.row_sum
	python -m grider.examples.matmul16_bf16
	python -m grider.examples.matmul
	python -m grider.examples.softmax
	python -m grider.examples.layer_norm
	python -m grider.examples.attention
	python -m grider.examples.mlp


benchmark:
	python -m grider.benchmark
