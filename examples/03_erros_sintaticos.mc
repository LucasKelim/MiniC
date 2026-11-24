// Exemplo 3: Testando detecção e recuperação de múltiplos erros sintáticos
int main() {
    int x = 10   // faltou ';'
    int y = (2 + 3 * ;
    if x > 5) {
        print(x);
    }
    while (y < 10 {
        y = y + 1;
    }
    return 0;
}
