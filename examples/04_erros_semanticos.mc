// Exemplo 4: Testando detecção de múltiplos erros semânticos
int soma(int a, int b) {
    return a + b;
}

int main() {
    int x = 10;
    int x = 20;               // erro 1: redeclaração no mesmo escopo
    int y = z + 1;            // erro 2: variável 'z' não declarada
    int n = 3.14;             // erro 3: float não pode ser atribuído a int
    int r = soma(1);          // erro 4: quantidade incorreta de argumentos
    if (x + 1) {              // erro 5: condição do if não é bool
        print(x);
    }
    int k = soma + 2;         // erro 6: uso de função como variável
    return "texto";           // erro 7: tipo de retorno incompatível
}
