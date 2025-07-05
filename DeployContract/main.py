from web3 import Web3, EthereumTesterProvider
from eth_tester import PyEVMBackend
from solcx import install_solc, compile_source
import time
install_solc(version='0.5.0')


w3 = Web3(EthereumTesterProvider(ethereum_tester=PyEVMBackend()))

compiled_sol = compile_source(
    '''
pragma solidity ^0.5.0;

contract TestAddMultiCost {

    uint256 a;
    uint256 b;
    uint256 c;

    constructor(uint256 x, uint256 y) public {
        a = x;
        b = y;
    }

    function AddMulti() public {
        int j=10000;
        while(j > 0){
            c = a + b;
            c = a * b;
            j--;
        }
    }

}
    ''',
    output_values=['abi', 'bin'],
    solc_version="0.5.0"
)

contract_id, contract_interface = compiled_sol.popitem()
bytecode = contract_interface['bin']
print(bytecode)
abi = contract_interface['abi']
print(abi)
w3.eth.default_account = w3.eth.accounts[0]
print(w3.eth.accounts)

Greeter = w3.eth.contract(abi=abi, bytecode=bytecode)

tx_hash = Greeter.constructor(1234, 4321).transact()
tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

print(tx_receipt)

greeter = w3.eth.contract(
    address=tx_receipt.contractAddress,
    abi=abi
)

t1 = time.time()
tx_hash = greeter.functions.AddMulti().transact()
t2 = time.time()
print((t2-t1)/10000)

tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)


