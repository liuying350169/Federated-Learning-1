port=9000
( CUDA_VISIBLE_DEVICES="" python ea_server.py $port & );
for i in {1..2}
do
        ( CUDA_VISIBLE_DEVICES="" python ea_client.py $port & );
done