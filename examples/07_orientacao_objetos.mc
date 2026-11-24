// Exemplo 7: Orientação a Objetos em MiniC
// Demonstra: class, public/private, construtor, new, this, null e métodos.

class ContaBancaria {
    public int numero;
    private string titular;
    private float saldo;

    public ContaBancaria(int num, string nome, float saldoInicial) {
        this.numero = num;
        this.titular = nome;
        this.saldo = saldoInicial;
    }

    private bool validarValor(float valor) {
        return valor > 0.0;
    }

    public void depositar(float valor) {
        if (this.validarValor(valor)) {
            this.saldo = this.saldo + valor;
        }
    }

    public bool sacar(float valor) {
        if (this.validarValor(valor) && valor <= this.saldo) {
            this.saldo = this.saldo - valor;
            return true;
        }
        return false;
    }

    public float getSaldo() {
        return this.saldo;
    }

    public void exibir() {
        print("Conta", this.numero, "-", this.titular, "| Saldo:", this.saldo);
    }
}

int main() {
    ContaBancaria c1 = new ContaBancaria(101, "Lucas", 500.0);
    ContaBancaria c2 = null;

    if (c2 == null) {
        print("c2 ainda nao foi inicializada");
    }

    c1.exibir();
    c1.depositar(250);      // coerção implícita int -> float!
    bool ok = c1.sacar(125.5);
    print("Saque realizado:", ok);
    print("Saldo final:", c1.getSaldo());
    return 0;
}
