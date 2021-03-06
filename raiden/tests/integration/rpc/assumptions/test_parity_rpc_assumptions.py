from typing import Any, Dict

import pytest

from raiden.network.rpc.client import JSONRPCClient
from raiden.tests.utils.smartcontracts import deploy_rpc_test_contract

pytestmark = pytest.mark.usefixtures("skip_if_not_parity")

# set very low values to force the client to prune old state
STATE_PRUNING = {
    "pruning": "fast",
    "pruning-history": 1,
    "pruning-memory": 1,
    "cache-size-db": 1,
    "cache-size-blocks": 1,
    "cache-size-queue": 1,
    "cache-size": 1,
}


@pytest.mark.parametrize("blockchain_extra_config", [STATE_PRUNING])
def test_parity_request_pruned_data_raises_an_exception(deploy_client: JSONRPCClient) -> None:
    """ Interacting with an old block identifier with a pruning client throws. """
    contract_proxy, _ = deploy_rpc_test_contract(deploy_client, "RpcWithStorageTest")
    iterations = 1000

    def send_transaction() -> Dict[str, Any]:
        estimated_transaction = deploy_client.estimate_gas(
            contract_proxy, "waste_storage", {}, iterations
        )
        assert estimated_transaction
        transaction = deploy_client.transact(estimated_transaction)
        return deploy_client.poll_transaction(transaction)

    first_receipt = send_transaction()
    pruned_block_number = first_receipt["blockNumber"]

    for _ in range(10):
        send_transaction()

    with pytest.raises(ValueError):
        contract_proxy.functions.const().call(block_identifier=pruned_block_number)

    with pytest.raises(ValueError):
        contract_proxy.functions.get(1).call(block_identifier=pruned_block_number)
