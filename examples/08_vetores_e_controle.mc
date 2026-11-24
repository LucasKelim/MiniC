// Exemplo 8: Vetores, const, break, continue, ++/-- e atribuição composta (+=, -=)

const int TAM = 5;

void ordenar(int[] v) {
    for (int i = 0; i < v.length; i++) {
        for (int j = 0; j < v.length - 1 - i; j++) {
            if (v[j] > v[j + 1]) {
                int tmp = v[j];
                v[j] = v[j + 1];
                v[j + 1] = tmp;
            }
        }
    }
}

int main() {
    int[] nums = new int[TAM];
    nums[0] = 42;
    nums[1] = 7;
    nums[2] = 19;
    nums[3] = 3;
    nums[4] = 25;

    ordenar(nums);

    int soma = 0;
    for (int i = 0; i < nums.length; i++) {
        if (nums[i] == 7) {
            continue;  // pula o 7
        }
        soma += nums[i];
        print("nums[", i, "] =", nums[i]);
        if (nums[i] == 25) {
            break;     // para no 25
        }
    }
    print("Soma parcial:", soma);
    return 0;
}
