// Exemplo 6: Demonstração das otimizações da Fase 5
float calcularPosicao(float inicial, float taxa) {
    float posicao = inicial + taxa * 60;
    return posicao;
}

int main() {
    // 1. Dobra e propagação de constantes
    int base = 2 + 3 * 4;
    int dobro = base * 2;

    // 2. Simplificações algébricas (identidades)
    int x = dobro + 0;
    int y = x * 1;
    int z = y * 0;

    // 3. Ramo morto (condição sempre falsa)
    if (10 < 5) {
        print("Nunca sera executado");
    }

    float pos = calcularPosicao(10.0, 2.5);
    print("Resultado:", y, z, pos);
    return 0;

    // 4. Código inalcançável após return
    int morto = 999;
    print(morto);
}
