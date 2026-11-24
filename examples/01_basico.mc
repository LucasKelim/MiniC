// Exemplo 1: Expressão clássica dos slides + função + controle de fluxo
float calcularPosicao(float inicial, float taxa) {
    float posicao = inicial + taxa * 60;
    return posicao;
}

/* Programa principal */
int main() {
    float p = calcularPosicao(10.5, 2.5);
    if (p >= 100.0 && p != 0.0) {
        print("Posicao final:\n");
        print(p);
    }
    return 0;
}
