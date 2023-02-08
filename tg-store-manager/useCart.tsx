import {useState} from 'react';

import _keys from 'lodash-es/keys';
import _values from 'lodash-es/values';
import _pick from 'lodash-es/pick';
import _sum from 'lodash-es/sum';
import stringify from 'json-stable-stringify';

import {getSubprodsMap, getOptionsMap, getProdPrice} from './useProducts';
import type {Product, ProdsMap, OptionsMap} from './useProducts';
import useCache from './useCache';
import type {Scalars} from '../utils/graphql';


export type Cart = {
    [itemId: string]: CartItemInfo
};

export type CartItemFormula = {
    prodId: Scalars['uuid'];
    additions: Additions
};

export type Additions = {
    [prodId: string]: number
};

export type CartItemInfo = {
    count: number;
    product: Product;
    price: number;
    discPrice: number
};

export type ChangeCart =
        (id: string, count: number, product?: Product) => boolean;

export type ChangeCiCount = (count: number) => ReturnType<ChangeCart>;

export type GetProdCount = (
    product: Product,
    formula?: Additions | string
) => [
    number,
    ChangeCiCount,
    string
];

export type GetCartCost = () => number;
export type ClearCart = () => void;
export type DeleteProd = (prodId: Scalars['uuid']) => void;
export type GetCartAddns = (itemId: string) => [ProdsMap, OptionsMap];


// Получить ИД товара для корзины
// NOTE Порядок одних и тех же свойств в объекте может отличаться
const getProdId = (product: Product, additions: Additions = {}) =>
    stringify({prodId: product.id, additions});


export default function useCart(
    changeCache?: ReturnType<typeof useCache>[1],
    init: Cart = {}
) {
    const [cart, setCart] = useState<Cart>(init);

    const changeCart: ChangeCart = (id, count, product) => {
        console.assert(count >= 0);

        setCart(prevCart => {
            const newCart = {...prevCart};

            if (count > 0) {
                if (!product) {
                    throw 'A product is undefined, but count is greater ' +
                            'then 0';
                }

                const prodCfg: CartItemFormula = JSON.parse(id);
                const [price, discPrice] = getProdPrice(
                        product, 1, prodCfg.additions);

                newCart[id] = {count, product, price, discPrice};
            }
            else
                delete newCart[id];

            changeCache?.({cart: newCart});
            return newCart;
        });

        return false;
    }

    const clearCart: ClearCart = () => {
        setCart({});
        changeCache?.({cart: {}});
    }

    const deleteProd: DeleteProd = id => changeCart(id, 0);

    const getProdCount: GetProdCount = (product, formula = {}) => {
        const id = typeof formula === 'string'
                ? formula : getProdId(product, formula);

        return [
            cart[id]?.count || 0,
            count => changeCart(id, count, product),
            id
        ];
    }

    // Получить объекты добавленных допов
    const getCartAddns: GetCartAddns = id => {
        const product = cart[id].product;
        const addnIds = _keys(JSON.parse(id).additions);

        return [
            _pick(getSubprodsMap(product), addnIds),
            _pick(getOptionsMap(product), addnIds)
        ];
    }

    const sumEachItem = (convert: (item: CartItemInfo) => number) =>
            _sum(_values(cart).map(item => item.count * convert(item)));

    const getCartCost: GetCartCost = () => sumEachItem(item => item.discPrice);
    const getCartDisc = () => sumEachItem(item => item.discPrice - item.price);

    return {
        cart,
        changeCart,
        setCart,
        clearCart,
        deleteProd,
        getProdCount,
        getCartAddns,
        getCartCost,
        getCartDisc
    };
}
