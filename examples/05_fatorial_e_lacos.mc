// Exemplo 5: Recursão (fatorial), laços for/while e expressões com float
int fatorial(int n) {
    if (n <= 1) {
        return 1;
    }
    return n * fatorial(n - 1);
}

int main() {
    int soma = 0;
    for (int i = 1; i <= 5; i = i + 1) {
        soma = soma + i;
    }
    print("Soma 1..5 =", soma);

    int f = fatorial(5);
    print("5! =", f);

    int k = 3;
    while (k > 0) {
        print("Contagem:", k);
        k = k - 1;
    }
    return 0;
}
